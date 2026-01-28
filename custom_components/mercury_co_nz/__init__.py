"""The Mercury Energy NZ integration."""
from __future__ import annotations

import logging
from pathlib import Path
from datetime import timedelta

from aiohttp import web
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.http import HomeAssistantView
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, DEFAULT_SCAN_INTERVAL, URL_BASE
from .coordinator import MercuryDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]

# Allowed JS filenames (no path traversal)
ALLOWED_JS_FILES = frozenset({
    "core.js",
    "styles.js",
    "energy-usage-card.js",
    "energy-weekly-summary-card.js",
    "energy-monthly-summary-card.js",
})


class MercuryStaticView(HomeAssistantView):
    """Serve Mercury card and shared JS files."""

    url = f"{URL_BASE}/{{filename:.+}}"
    name = "mercury_static"
    requires_auth = False

    def __init__(self, component_dir: Path) -> None:
        self._component_dir = component_dir

    async def get(self, request: web.Request, **kwargs) -> web.Response:
        """Serve the requested file if allowed."""
        filename = request.match_info.get("filename", "")
        if filename not in ALLOWED_JS_FILES:
            return self.json_message("Not found", 404)
        file_path = self._component_dir / filename
        if not file_path.is_file():
            return self.json_message("Not found", 404)
        return web.FileResponse(file_path)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register static file view at startup so /api/mercury_co_nz/* works before config entry.
    Add 'mercury_co_nz:' to configuration.yaml to load this and enable the card URLs at boot.
    """
    component_dir = Path(__file__).parent
    hass.http.register_view(MercuryStaticView(component_dir))
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Mercury Energy NZ from a config entry."""
    _LOGGER.info(
        "Setting up Mercury integration (entry_id=%s, unique_id=%s)",
        entry.entry_id,
        entry.unique_id,
    )
    hass.data.setdefault(DOMAIN, {})

    # Serve card JS via a View (avoids static path quirks)
    component_dir = Path(__file__).parent
    hass.http.register_view(MercuryStaticView(component_dir))

    # Register card URLs as Lovelace resources (storage mode) so dashboards load them
    from .frontend import LovelaceResourceRegistration
    registrar = LovelaceResourceRegistration(hass)
    await registrar.async_register()

    coordinator = MercuryDataUpdateCoordinator(
        hass,
        entry.data,
        update_interval=timedelta(minutes=DEFAULT_SCAN_INTERVAL),
    )

    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception as err:  # pylint: disable=broad-except
        _LOGGER.error(
            "Mercury API initial refresh failed (sensors will be created but unavailable): %s. "
            "Check your Mercury email/password in Settings → Devices & services → HACS → Mercury NZ, or delete and re-add the integration to re-enter credentials.",
            err,
        )
        # Continue so sensors are created; they will show unavailable until auth succeeds
        # User can reload the integration or re-add after fixing credentials

    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _LOGGER.info(
        "Mercury integration setup complete; sensors (e.g. sensor.mercury_nz_energy_usage) should appear in Developer Tools → States.",
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        coordinator = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        if coordinator is not None:
            await coordinator.async_close()
    return unload_ok
