"""Coordinator that forwards selected entities to the backend.

HomeWizard entities are polled directly at 1 Hz (genuine sampling). Other
entities are forwarded on Home Assistant state changes only.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta
import logging
import time

from homeassistant.const import CONF_IP_ADDRESS, CONF_TOKEN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval

from .const import (
    DIRECT_HOMEWIZARD_POLL_INTERVAL_SECONDS,
    DIRECT_HOMEWIZARD_REQUEST_TIMEOUT_SECONDS,
)
from .ha_power_collector import HAPowerCollector
from .models import Measurement
from .socketio_client import PowerChaingerSocketClient

_LOGGER = logging.getLogger(__name__)
NS_PER_SECOND = 1_000_000_000

HOMEWIZARD_POWER_FIELDS = {
    "active_power_w": "power_w",
    "active_power_l1_w": "power_l1_w",
    "active_power_l2_w": "power_l2_w",
    "active_power_l3_w": "power_l3_w",
    "active_production_power_w": "power_w",
}


@dataclass
class _HomeWizardBinding:
    entity_id: str
    entity_name: str
    device_id: str | None
    serial: str
    config_entry_id: str
    sensor_key: str


@dataclass
class _HomeWizardClientInfo:
    ip_address: str
    token: str | None
    client: object | None = None
    last_warning_ts: float = 0.0


class PowerChaingerCoordinator:
    """Split ingest: HomeWizard direct polling and HA state-change forwarding."""

    def __init__(
        self,
        hass: HomeAssistant,
        collector: HAPowerCollector,
        socket_client: PowerChaingerSocketClient,
    ) -> None:
        self._hass = hass
        self._collector = collector
        self._socket_client = socket_client
        self._unsub_state_events = None
        self._unsub_homewizard_poll = None
        self._event_entities: set[str] = set()
        self._homewizard_bindings: dict[str, _HomeWizardBinding] = {}
        self._homewizard_clients: dict[str, _HomeWizardClientInfo] = {}
        self._homewizard_poll_running = False

    async def async_start(self) -> None:
        entity_ids = self._collector.selected_entities()
        self._classify_selected_entities(entity_ids)
        self._unsub_state_events = async_track_state_change_event(
            self._hass,
            entity_ids,
            self._handle_state_change,
        )
        if self._homewizard_bindings:
            self._unsub_homewizard_poll = async_track_time_interval(
                self._hass,
                self._async_poll_homewizard_entities,
                timedelta(seconds=DIRECT_HOMEWIZARD_POLL_INTERVAL_SECONDS),
            )
        _LOGGER.info(
            (
                "Powerchainger started for %s entities: %s HomeWizard direct-polled, "
                "%s event-forwarded"
            ),
            len(entity_ids),
            len(self._homewizard_bindings),
            len(self._event_entities),
        )

    def _classify_selected_entities(self, entity_ids: list[str]) -> None:
        registry = er.async_get(self._hass)
        self._event_entities.clear()
        self._homewizard_bindings.clear()
        self._homewizard_clients.clear()

        for entity_id in entity_ids:
            self._event_entities.add(entity_id)
            entry = registry.async_get(entity_id)
            if entry is None or entry.platform != "homewizard" or not entry.config_entry_id:
                continue
            config_entry = self._hass.config_entries.async_get_entry(entry.config_entry_id)
            if config_entry is None:
                continue
            ip_address = config_entry.data.get(CONF_IP_ADDRESS)
            if not ip_address:
                _LOGGER.debug("Skipping HomeWizard entity %s without ip address", entity_id)
                continue
            sensor_key = self._extract_homewizard_sensor_key(entry.unique_id)
            if sensor_key is None:
                _LOGGER.debug(
                    "Skipping HomeWizard entity %s with unsupported unique_id=%s",
                    entity_id,
                    entry.unique_id,
                )
                continue
            state = self._hass.states.get(entity_id)
            entity_name = str(state.name) if state and state.name else entity_id
            serial = self._serial_for_homewizard_entry(config_entry.unique_id, entity_name)
            self._homewizard_bindings[entity_id] = _HomeWizardBinding(
                entity_id=entity_id,
                entity_name=entity_name,
                device_id=entry.device_id,
                serial=serial,
                config_entry_id=config_entry.entry_id,
                sensor_key=sensor_key,
            )
            self._homewizard_clients.setdefault(
                config_entry.entry_id,
                _HomeWizardClientInfo(
                    ip_address=ip_address,
                    token=config_entry.data.get(CONF_TOKEN),
                ),
            )
            self._event_entities.discard(entity_id)

    @staticmethod
    def _serial_for_homewizard_entry(config_unique_id: str | None, fallback: str) -> str:
        if not config_unique_id:
            return fallback
        if "_" not in config_unique_id:
            return config_unique_id
        return config_unique_id.split("_", 1)[1]

    @staticmethod
    def _extract_homewizard_sensor_key(unique_id: str | None) -> str | None:
        if not unique_id:
            return None
        for key in HOMEWIZARD_POWER_FIELDS:
            if unique_id.endswith(f"_{key}"):
                return key
        return None

    @staticmethod
    def _extract_entity_id(event) -> str | None:
        return event.data.get("entity_id")

    @staticmethod
    def _extract_new_state(event):
        return event.data.get("new_state")

    def _handle_state_change(self, event) -> None:
        self._hass.add_job(self._async_process_state_change, event)

    async def _async_process_state_change(self, event) -> None:
        try:
            entity_id = self._extract_entity_id(event)
            new_state = self._extract_new_state(event)

            if entity_id is None:
                return
            if entity_id not in self._event_entities:
                return
            sample = await self._collector.sample_from_state(entity_id, new_state)
            if sample is None:
                return
            timestamp = int(new_state.last_updated.timestamp() * NS_PER_SECOND)
            measurement = Measurement(
                user_id=sample.user_id,
                timestamp=timestamp,
                serial=sample.serial,
                wattage=sample.wattage,
                entity_id=sample.entity_id,
                entity_name=sample.entity_name,
                device_id=sample.device_id,
            )
            await self._socket_client.send_many([measurement])
        except Exception as err:  # pragma: no cover - safety net in event callback
            _LOGGER.exception("Powerchainger event processing failed: %s", err)

    async def _async_poll_homewizard_entities(self, _now=None) -> None:
        if self._homewizard_poll_running:
            _LOGGER.debug("Skipping HomeWizard poll tick while previous poll is running")
            return
        self._homewizard_poll_running = True
        try:
            batch = await self._collect_homewizard_measurements()
            if batch:
                await self._socket_client.send_many(batch)
        except Exception as err:  # pragma: no cover - defensive timer callback
            _LOGGER.exception("HomeWizard direct poll failed: %s", err)
        finally:
            self._homewizard_poll_running = False

    async def _collect_homewizard_measurements(self) -> list[Measurement]:
        if not self._homewizard_bindings:
            return []
        payloads_by_entry: dict[str, object] = {}
        fetch_tasks = [
            self._fetch_homewizard_combined_with_timeout(entry_id, client_info)
            for entry_id, client_info in self._homewizard_clients.items()
        ]
        results = await asyncio.gather(*fetch_tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):  # pragma: no cover - defensive
                continue
            entry_id, payload = result
            if payload is not None:
                payloads_by_entry[entry_id] = payload

        now_ts = int(time.time() * NS_PER_SECOND)
        out: list[Measurement] = []
        for binding in self._homewizard_bindings.values():
            combined = payloads_by_entry.get(binding.config_entry_id)
            if combined is None:
                continue
            wattage = self._extract_homewizard_wattage(combined, binding.sensor_key)
            if wattage is None:
                continue
            out.append(
                Measurement(
                    user_id=self._collector.user_id,
                    timestamp=now_ts,
                    serial=binding.serial,
                    wattage=wattage,
                    entity_id=binding.entity_id,
                    entity_name=binding.entity_name,
                    device_id=binding.device_id,
                )
            )
        return out

    async def _fetch_homewizard_combined_with_timeout(
        self,
        entry_id: str,
        client_info: _HomeWizardClientInfo,
    ) -> tuple[str, object | None]:
        try:
            payload = await asyncio.wait_for(
                self._fetch_homewizard_combined(client_info),
                timeout=DIRECT_HOMEWIZARD_REQUEST_TIMEOUT_SECONDS,
            )
            return entry_id, payload
        except TimeoutError:
            self._log_homewizard_poll_warning(
                client_info,
                RuntimeError(
                    f"timeout after {DIRECT_HOMEWIZARD_REQUEST_TIMEOUT_SECONDS}s"
                ),
            )
            return entry_id, None

    async def _fetch_homewizard_combined(self, client_info: _HomeWizardClientInfo):
        try:
            client = await self._get_or_create_homewizard_client(client_info)
            return await client.combined()
        except Exception as err:
            self._log_homewizard_poll_warning(client_info, err)
            if client_info.client is not None:
                try:
                    await client_info.client.close()
                except Exception:  # pragma: no cover
                    pass
                client_info.client = None
            return None

    async def _get_or_create_homewizard_client(self, client_info: _HomeWizardClientInfo):
        if client_info.client is not None:
            return client_info.client
        try:
            from homewizard_energy import HomeWizardEnergyV1, HomeWizardEnergyV2
        except ImportError as err:
            raise RuntimeError(
                "homewizard_energy dependency is unavailable; cannot direct-poll HomeWizard"
            ) from err
        # Match Home Assistant core behavior: V1 devices do not use token auth.
        if client_info.token:
            client_info.client = HomeWizardEnergyV2(
                client_info.ip_address,
                token=client_info.token,
            )
        else:
            client_info.client = HomeWizardEnergyV1(client_info.ip_address)
        return client_info.client

    def _log_homewizard_poll_warning(self, client_info: _HomeWizardClientInfo, err: Exception) -> None:
        # Avoid log storms when the same endpoint fails every second.
        now = time.time()
        if now - client_info.last_warning_ts < 60:
            return
        client_info.last_warning_ts = now
        _LOGGER.warning(
            "HomeWizard poll failed for ip=%s (will retry): %s",
            client_info.ip_address,
            err,
        )

    @staticmethod
    def _extract_homewizard_wattage(combined, sensor_key: str) -> float | None:
        measurement = getattr(combined, "measurement", None)
        if measurement is None:
            return None
        field = HOMEWIZARD_POWER_FIELDS.get(sensor_key)
        if field is None:
            return None
        value = getattr(measurement, field, None)
        if value is None:
            return None
        watt = float(value)
        if sensor_key == "active_production_power_w":
            return -watt
        return watt

    async def async_stop(self) -> None:
        if self._unsub_homewizard_poll is not None:
            self._unsub_homewizard_poll()
            self._unsub_homewizard_poll = None
        if self._unsub_state_events is not None:
            self._unsub_state_events()
            self._unsub_state_events = None
        for client_info in self._homewizard_clients.values():
            if client_info.client is None:
                continue
            try:
                await client_info.client.close()
            except Exception as err:  # pragma: no cover - cleanup path
                _LOGGER.debug("HomeWizard client close failed: %s", err)
            client_info.client = None
        await self._socket_client.shutdown()
