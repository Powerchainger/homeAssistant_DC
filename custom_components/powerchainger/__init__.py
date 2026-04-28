"""Powerchainger Home Assistant integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_DRY_RUN,
    CONF_SEND_DATA,
    CONF_SELECTED_ENTITIES,
    CONF_USER,
    CONF_WEBSOCKET_URL,
    DEFAULT_WEBSOCKET_URL,
    DOMAIN,
)
from .coordinator import PowerChaingerCoordinator
from .ha_power_collector import HAPowerCollector
from .socketio_client import PowerChaingerSocketClient

_LOGGER = logging.getLogger(__name__)


async def async_setup(_hass: HomeAssistant, _config: dict) -> bool:
    """Set up via config entries only."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Powerchainger from a config entry."""
    data = entry.data
    user = data[CONF_USER]
    websocket_url = data.get(CONF_WEBSOCKET_URL, DEFAULT_WEBSOCKET_URL)
    send_data = data.get(CONF_SEND_DATA)
    if send_data is None:
        # Backward compatibility with old entries that only stored dry_run.
        dry_run = data.get(CONF_DRY_RUN, True)
    else:
        dry_run = not send_data
    selected_entities = data.get(CONF_SELECTED_ENTITIES, [])

    if not selected_entities:
        _LOGGER.warning(
            "Powerchainger is configured but no power entities are selected. "
            "Open integration options to choose entities."
        )

    collector = HAPowerCollector(
        hass=hass,
        user_id=user,
        selected_entities=selected_entities,
    )
    if dry_run:
        _LOGGER.info("Powerchainger send data is disabled; outbound forwarding is turned off")
    socket_client = PowerChaingerSocketClient(
        websocket_url=websocket_url,
        dry_run=dry_run,
    )
    coordinator = PowerChaingerCoordinator(
        hass=hass,
        collector=collector,
        socket_client=socket_client,
    )

    await coordinator.async_start()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator
    _LOGGER.info("Powerchainger integration setup complete")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a Powerchainger config entry."""
    coordinator = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    if coordinator is not None:
        await coordinator.async_stop()
    if not hass.data.get(DOMAIN):
        hass.data.pop(DOMAIN, None)
    return True
