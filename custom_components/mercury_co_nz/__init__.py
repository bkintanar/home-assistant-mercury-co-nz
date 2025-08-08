"""The Mercury Energy NZ integration."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig

from .const import DOMAIN, DEFAULT_SCAN_INTERVAL
from .coordinator import MercuryDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Mercury Energy NZ from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    # Register the frontend card when the integration is set up
    await hass.http.async_register_static_paths([
        StaticPathConfig(
            f"/api/{DOMAIN}/chartjs-custom-card.js",
            hass.config.path(f"custom_components/{DOMAIN}/custom-chart-card.js"),
            True,
        )
    ])

    # Add the JS file to frontend
    add_extra_js_url(hass, f"/api/{DOMAIN}/chartjs-custom-card.js")

    coordinator = MercuryDataUpdateCoordinator(
        hass,
        entry.data,
        update_interval=timedelta(minutes=DEFAULT_SCAN_INTERVAL),
    )

    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        coordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_close()

    return unload_ok
