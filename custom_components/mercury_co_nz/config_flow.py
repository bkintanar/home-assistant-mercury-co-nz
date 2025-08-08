"""Config flow for Mercury Energy NZ integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN, CONF_EMAIL
from .mercury_api import MercuryAPI

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


class MercuryConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Mercury Energy NZ."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Validate the user input
            try:
                session = async_get_clientsession(self.hass)
                api = MercuryAPI(
                    session,
                    user_input[CONF_EMAIL],
                    user_input[CONF_PASSWORD],
                )

                # Test the connection
                await api.authenticate()

            except Exception as exc:  # pylint: disable=broad-except
                _LOGGER.error("Unable to connect to Mercury Energy: %s", exc)
                errors["base"] = "cannot_connect"
            else:
                # Create the config entry
                await self.async_set_unique_id(user_input[CONF_EMAIL])
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=f"Mercury Energy - {user_input[CONF_EMAIL]}",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )
