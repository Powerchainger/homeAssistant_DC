"""Coordinator that forwards on Home Assistant state-change events."""

from __future__ import annotations

import logging
import time

from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_state_change_event

from .ha_power_collector import HAPowerCollector, Measurement
from .socketio_client import PowerChaingerSocketClient

_LOGGER = logging.getLogger(__name__)


class PowerChaingerCoordinator:
    """Event-driven coordinator for selected entities."""

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
        self._entity_is_active: dict[str, bool] = {}

    async def async_start(self) -> None:
        entity_ids = self._collector.selected_entities()
        self._unsub_state_events = async_track_state_change_event(
            self._hass,
            entity_ids,
            self._handle_state_change,
        )
        _LOGGER.info("Powerchainger event listener started for %s selected entities", len(entity_ids))

    @staticmethod
    def _extract_entity_id(event) -> str | None:
        return event.data.get("entity_id")

    @staticmethod
    def _extract_new_state(event):
        return event.data.get("new_state")

    def _handle_state_change(self, event) -> None:
        # state_changed callbacks may arrive off the event loop thread;
        # add_job is the HA thread-safe way to schedule coroutine work.
        self._hass.add_job(self._async_process_state_change, event)

    async def _async_process_state_change(self, event) -> None:
        try:
            entity_id = self._extract_entity_id(event)
            new_state = self._extract_new_state(event)

            if entity_id is None:
                return
            measurement = await self._collector.measurement_from_state(entity_id, new_state)
            if measurement is None:
                return
            current_is_active = measurement.wattage > 0
            previous_is_active = self._entity_is_active.get(entity_id, False)

            outbound: list[Measurement] = []
            if current_is_active and not previous_is_active:
                # Guarded pre-activation marker: emit one synthetic 0 only on idle->active.
                outbound.append(measurement.with_wattage(0.0, int(time.time() * 1_000_000_000)))
            outbound.append(measurement)

            self._entity_is_active[entity_id] = current_is_active
            await self._socket_client.send_many(outbound)
        except Exception as err:  # pragma: no cover - safety net in event callback
            _LOGGER.exception("Powerchainger event processing failed: %s", err)

    async def async_stop(self) -> None:
        if self._unsub_state_events is not None:
            self._unsub_state_events()
            self._unsub_state_events = None
        await self._socket_client.shutdown()
