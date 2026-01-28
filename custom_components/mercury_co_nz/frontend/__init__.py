"""Lovelace resource registration for Mercury Energy NZ custom cards."""

from __future__ import annotations

import logging

from homeassistant.components.lovelace.const import LOVELACE_DATA
from homeassistant.core import HomeAssistant

from ..const import JSMODULES, URL_BASE

_LOGGER = logging.getLogger(__name__)


class LovelaceResourceRegistration:
    """Registers Mercury card JavaScript modules as Lovelace resources."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the registrar."""
        self.hass = hass
        self.lovelace = self.hass.data.get(LOVELACE_DATA)

    async def async_register(self) -> None:
        """Register frontend resources with Lovelace (storage mode only)."""
        if self.lovelace is None:
            _LOGGER.debug("Lovelace not loaded yet, skipping resource registration")
            return
        if self.lovelace.mode != "storage":
            _LOGGER.debug(
                "Lovelace mode is %s; resources only auto-register in storage mode",
                self.lovelace.mode,
            )
            return
        await self._async_wait_for_lovelace_resources()

    async def _async_wait_for_lovelace_resources(self) -> None:
        """Load Lovelace resources (if needed) and register card modules."""
        self.hass.async_create_task(self._async_register_modules())

    async def _async_register_modules(self) -> None:
        """Register or update JavaScript modules in Lovelace resources."""
        # Ensure storage collection is loaded before reading/creating items
        if hasattr(self.lovelace.resources, "async_load") and not getattr(
            self.lovelace.resources, "loaded", True
        ):
            await self.lovelace.resources.async_load()
        try:
            existing = [
                r
                for r in self.lovelace.resources.async_items()
                if r.get("url", "").startswith(URL_BASE)
            ]
        except Exception as e:
            _LOGGER.warning("Could not list Lovelace resources: %s", e)
            return

        for module in JSMODULES:
            url = f"{URL_BASE}/{module['filename']}"
            versioned_url = f"{url}?v={module['version']}"
            registered = False
            for resource in existing:
                if self._get_path(resource.get("url", "")) == url:
                    registered = True
                    if self._get_version(resource.get("url", "")) != module["version"]:
                        _LOGGER.info(
                            "Updating %s to version %s",
                            module["name"],
                            module["version"],
                        )
                        try:
                            await self.lovelace.resources.async_update_item(
                                resource["id"],
                                {"res_type": "module", "url": versioned_url},
                            )
                        except Exception as e:
                            _LOGGER.warning("Failed to update resource %s: %s", url, e)
                    break
            if not registered:
                _LOGGER.info(
                    "Registering %s version %s",
                    module["name"],
                    module["version"],
                )
                try:
                    await self.lovelace.resources.async_create_item(
                        {"res_type": "module", "url": versioned_url}
                    )
                except Exception as e:
                    _LOGGER.warning("Failed to create resource %s: %s", url, e)

    @staticmethod
    def _get_path(url: str) -> str:
        """Extract path without query parameters."""
        return url.split("?")[0]

    @staticmethod
    def _get_version(url: str) -> str:
        """Extract version from URL query string."""
        parts = url.split("?")
        if len(parts) > 1 and "v=" in parts[1]:
            for param in parts[1].split("&"):
                if param.startswith("v="):
                    return param[2:]
        return "0"
