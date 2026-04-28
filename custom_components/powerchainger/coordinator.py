"""Coordinator that polls and forwards HomeWizard measurements."""

from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval

from .ha_power_collector import HAPowerCollector
from .socketio_client import PowerChaingerSocketClient

_LOGGER = logging.getLogger(__name__)


class PowerChaingerCoordinator:
    """Background coordinator for 1s measurement forwarding."""

    def __init__(
        self,
        hass: HomeAssistant,
        collector: HAPowerCollector,
        socket_client: PowerChaingerSocketClient,
        scan_interval_seconds: int,
    ) -> None:
        self._hass = hass
        self._collector = collector
        self._socket_client = socket_client
        self._scan_interval = timedelta(seconds=scan_interval_seconds)
        self._unsub_interval = None

    async def async_start(self) -> None:
        self._unsub_interval = async_track_time_interval(
            self._hass, self._async_tick, self._scan_interval
        )
        _LOGGER.info("Powerchainger coordinator started with interval=%ss", self._scan_interval.total_seconds())
        # Run immediately once so first datapoint is not delayed by one full interval.
        await self._async_tick(None)

    async def _async_tick(self, _now) -> None:
        try:
            measurements = await self._collector.collect()
            await self._socket_client.send_many(measurements)
            if measurements:
                _LOGGER.debug("Forwarded %s measurement(s)", len(measurements))
        except Exception as err:  # pragma: no cover - safety net in scheduler callback
            _LOGGER.exception("Powerchainger tick failed: %s", err)

    async def async_stop(self) -> None:
        if self._unsub_interval is not None:
            self._unsub_interval()
            self._unsub_interval = None
        await self._socket_client.shutdown()
