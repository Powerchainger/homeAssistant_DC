"""Collect power measurements from Home Assistant entities."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er


@dataclass(slots=True)
class Measurement:
    user_id: str
    timestamp: int
    serial: str
    wattage: float
    entity_id: str
    entity_name: str
    device_id: str | None

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


class HAPowerCollector:
    """Collect measurements from selected Home Assistant power entities."""

    def __init__(
        self,
        hass: HomeAssistant,
        user_id: str,
        selected_entities: list[str],
    ) -> None:
        self._hass = hass
        self._user_id = user_id
        self._entity_ids = selected_entities
        self._entity_ids_set = set(selected_entities)
        self._last_forwarded_updated: dict[str, str] = {}

    def selected_entities(self) -> list[str]:
        return self._entity_ids

    async def measurement_from_state(self, entity_id: str, state) -> Measurement | None:
        if entity_id not in self._entity_ids_set or state is None:
            return None

        try:
            wattage = float(state.state)
        except (TypeError, ValueError):
            return None

        source_updated = str(state.last_updated)
        if self._last_forwarded_updated.get(entity_id) == source_updated:
            return None

        self._last_forwarded_updated[entity_id] = source_updated
        entity_registry = er.async_get(self._hass)
        entry = entity_registry.async_get(entity_id)
        entity_name = state.name or entity_id
        device_id = entry.device_id if entry else None
        return Measurement(
            user_id=self._user_id,
            timestamp=int(time.time() * 1_000_000_000),
            serial=str(entity_name),
            wattage=wattage,
            entity_id=entity_id,
            entity_name=str(entity_name),
            device_id=device_id,
        )
