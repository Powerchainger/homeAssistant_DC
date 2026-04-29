"""Async Socket.IO forwarding with reconnect-safe buffering.

When disconnected, measurements are held in ``_buffer`` until the next successful
send. Sampling semantics (HomeWizard direct 1 Hz polling vs event-driven forwarding)
live in ``coordinator.PowerChaingerCoordinator``, not here.
"""

from __future__ import annotations

from collections import deque
import logging

import socketio

from .const import DEFAULT_BUFFER_MAX_SIZE
from .models import Measurement

_LOGGER = logging.getLogger(__name__)


class PowerChaingerSocketClient:
    """Socket.IO client that forwards data to the datacollection backend contract."""

    def __init__(
        self,
        websocket_url: str,
        dry_run: bool = True,
        buffer_max_size: int = DEFAULT_BUFFER_MAX_SIZE,
    ) -> None:
        self._url = websocket_url
        self._dry_run = dry_run
        self._client = socketio.AsyncClient(reconnection=True, logger=False, engineio_logger=False)
        self._buffer: deque[Measurement] = deque(maxlen=buffer_max_size)
        self._connect_lock = False

    async def ensure_connected(self) -> bool:
        if self._client.connected:
            return True
        if self._connect_lock:
            return False

        self._connect_lock = True
        try:
            await self._client.connect(self._url)
            _LOGGER.info("Connected to Powerchainger websocket endpoint")
            return True
        except Exception as err:  # pragma: no cover - network-dependent path
            _LOGGER.warning("Socket.IO connection failed: %s", err)
            return False
        finally:
            self._connect_lock = False

    async def send_many(self, measurements: list[Measurement]) -> None:
        if not measurements:
            return
        if self._dry_run:
            preview = [
                {
                    "Serial": measurement.serial,
                    "EntityId": measurement.entity_id,
                    "EntityName": measurement.entity_name,
                    "DeviceId": measurement.device_id,
                    "Wattage": measurement.wattage,
                    "Timestamp": measurement.timestamp,
                }
                for measurement in measurements
            ]
            _LOGGER.info(
                "Send data is disabled; would forward %s measurement(s): %s",
                len(measurements),
                preview,
            )
            return
        connected = await self.ensure_connected()
        if not connected:
            self._buffer.extend(measurements)
            return

        if self._buffer:
            pending = list(self._buffer)
            self._buffer.clear()
            await self._emit_many(pending)
        await self._emit_many(measurements)

    async def _emit_many(self, measurements: list[Measurement]) -> None:
        for measurement in measurements:
            await self._client.emit("json", measurement.to_payload())

    async def shutdown(self) -> None:
        if self._client.connected:
            await self._client.disconnect()
