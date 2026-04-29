"""Wire-format models (no Home Assistant imports)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class PowerSample:
    """One HA reading placed in the emitter bucket for ``sample_unix_second``."""

    user_id: str
    entity_id: str
    entity_name: str
    serial: str
    device_id: str | None
    wattage: float
    sample_unix_second: int


@dataclass
class Measurement:
    user_id: str
    timestamp: int
    serial: str
    wattage: float
    entity_id: str
    entity_name: str
    device_id: str | None

    def with_wattage(self, wattage: float, timestamp: int | None = None) -> "Measurement":
        return Measurement(
            user_id=self.user_id,
            timestamp=self.timestamp if timestamp is None else timestamp,
            serial=self.serial,
            wattage=wattage,
            entity_id=self.entity_id,
            entity_name=self.entity_name,
            device_id=self.device_id,
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "UserId": self.user_id,
            "Timestamp": self.timestamp,
            "Serial": self.serial,
            "Wattage": self.wattage,
            "EntityId": self.entity_id,
            "EntityName": self.entity_name,
            "DeviceId": self.device_id,
        }
