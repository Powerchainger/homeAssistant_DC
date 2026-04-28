"""Config flow for Powerchainger."""

from __future__ import annotations

import random
import string
from typing import Any

import voluptuous as vol

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.const import UnitOfPower
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import SelectOptionDict, SelectSelector, SelectSelectorConfig

from .const import (
    CONF_DRY_RUN,
    CONF_SEND_DATA,
    CONF_SCAN_INTERVAL,
    CONF_SELECTED_ENTITIES,
    CONF_USER,
    CONF_WEBSOCKET_URL,
    DEFAULT_WEBSOCKET_URL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)


def _random_user() -> str:
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    return f"ha-user-{suffix}"


def _power_entity_options(hass: HomeAssistant) -> list[SelectOptionDict]:
    options: list[SelectOptionDict] = []
    for state in hass.states.async_all("sensor"):
        device_class = state.attributes.get("device_class")
        unit = state.attributes.get("unit_of_measurement")
        if device_class != SensorDeviceClass.POWER:
            continue
        if unit not in {UnitOfPower.WATT, UnitOfPower.KILO_WATT, "W", "kW"}:
            continue
        options.append(
            SelectOptionDict(
                value=state.entity_id,
                label=f"{state.name} ({state.entity_id})",
            )
        )
    options.sort(key=lambda item: item["label"])
    return options


def _full_schema(
    hass: HomeAssistant,
    default_send_data: bool,
    default_selected_entities: list[str] | None = None,
) -> vol.Schema:
    return vol.Schema(
        {
            vol.Optional(CONF_SEND_DATA, default=default_send_data): bool,
            vol.Required(
                CONF_SELECTED_ENTITIES,
                default=default_selected_entities or [],
            ): SelectSelector(
                SelectSelectorConfig(
                    options=_power_entity_options(hass),
                    multiple=True,
                    mode="dropdown",
                )
            )
        }
    )


class PowerChaingerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Powerchainger."""

    VERSION = 1

    def __init__(self) -> None:
        self._generated_user: str | None = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        """Initial flow step."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is not None:
            if self._generated_user is None:
                self._generated_user = _random_user()
            selected_entities = user_input.get(CONF_SELECTED_ENTITIES, [])
            send_data = user_input.get(CONF_SEND_DATA, False)
            entry_data = {
                CONF_USER: self._generated_user,
                CONF_WEBSOCKET_URL: DEFAULT_WEBSOCKET_URL,
                CONF_DRY_RUN: not send_data,
                CONF_SEND_DATA: send_data,
                CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
                CONF_SELECTED_ENTITIES: selected_entities,
            }
            return self.async_create_entry(title=f"Powerchainger ({self._generated_user})", data=entry_data)

        if self._generated_user is None:
            self._generated_user = _random_user()

        schema = _full_schema(
            hass=self.hass,
            default_send_data=False,
            default_selected_entities=[],
        )
        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            description_placeholders={"username": self._generated_user},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry):
        return PowerChaingerOptionsFlow(config_entry)


class PowerChaingerOptionsFlow(OptionsFlow):
    """Powerchainger options flow."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        """Edit runtime options in a single screen."""
        if user_input is not None:
            selected_entities = user_input.get(CONF_SELECTED_ENTITIES, [])
            send_data = user_input.get(CONF_SEND_DATA, False)
            self.hass.config_entries.async_update_entry(
                self._entry,
                data={
                    **self._entry.data,
                    CONF_SEND_DATA: send_data,
                    CONF_DRY_RUN: not send_data,
                    CONF_WEBSOCKET_URL: DEFAULT_WEBSOCKET_URL,
                    CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
                    CONF_SELECTED_ENTITIES: selected_entities,
                },
            )
            await self.hass.config_entries.async_reload(self._entry.entry_id)
            return self.async_create_entry(title="", data={})

        data = self._entry.data
        send_data = data.get(CONF_SEND_DATA, not data.get(CONF_DRY_RUN, True))
        schema = _full_schema(
            hass=self.hass,
            default_send_data=send_data,
            default_selected_entities=data.get(CONF_SELECTED_ENTITIES, []),
        )
        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            description_placeholders={"username": data.get(CONF_USER, "unknown")},
        )
