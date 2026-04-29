"""Collect power measurements from Home Assistant entities."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .models import PowerSample


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

    @property
    def user_id(self) -> str:
        return self._user_id

    def selected_entities(self) -> list[str]:
        return self._entity_ids

    async def sample_from_state(self, entity_id: str, state) -> PowerSample | None:
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
        sample_unix_second = int(state.last_updated.timestamp())
        return PowerSample(
            user_id=self._user_id,
            entity_id=entity_id,
            entity_name=str(entity_name),
            serial=str(entity_name),
            device_id=device_id,
            wattage=wattage,
            sample_unix_second=sample_unix_second,
        )
