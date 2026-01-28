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

    async def _validate_mercury(self, email: str, password: str) -> bool:
        """Validate credentials with Mercury API."""
        session = async_get_clientsession(self.hass)
        api = MercuryAPI(session, email, password)
        return await api.authenticate()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                ok = await self._validate_mercury(
                    user_input[CONF_EMAIL], user_input[CONF_PASSWORD]
                )
                if not ok:
                    errors["base"] = "cannot_connect"
            except Exception as exc:  # pylint: disable=broad-except
                _LOGGER.error("Unable to connect to Mercury Energy: %s", exc)
                errors["base"] = "cannot_connect"
            else:
                if not errors:
                    await self.async_set_unique_id(user_input[CONF_EMAIL])
                    # If already configured, offer to update password in-flow instead of aborting
                    existing = next(
                        (
                            e
                            for e in self.hass.config_entries.async_entries(DOMAIN)
                            if e.unique_id == user_input[CONF_EMAIL]
                        ),
                        None,
                    )
                    if existing:
                        self.context["entry_id"] = existing.entry_id
                        self.context["email"] = user_input[CONF_EMAIL]
                        return self.async_show_form(
                            step_id="already_configured_update",
                            data_schema=vol.Schema(
                                {
                                    vol.Required(
                                        CONF_EMAIL, default=user_input[CONF_EMAIL]
                                    ): str,
                                    vol.Required(CONF_PASSWORD): str,
                                }
                            ),
                            description_placeholders={
                                "email": user_input[CONF_EMAIL],
                            },
                        )
                    return self.async_create_entry(
                        title=f"Mercury NZ - {user_input[CONF_EMAIL]}",
                        data=user_input,
                    )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_already_configured_update(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Update password for an existing Mercury entry (shown when add finds same email)."""
        entry_id = self.context.get("entry_id")
        entry = (
            self.hass.config_entries.async_get_entry(entry_id) if entry_id else None
        )
        if not entry:
            return self.async_abort(reason="reconfigure_failed")

        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                ok = await self._validate_mercury(
                    user_input[CONF_EMAIL], user_input[CONF_PASSWORD]
                )
                if not ok:
                    errors["base"] = "cannot_connect"
            except Exception as exc:  # pylint: disable=broad-except
                _LOGGER.error("Unable to connect to Mercury Energy: %s", exc)
                errors["base"] = "cannot_connect"

            if not errors:
                # Remove the old entry and create a new one so HA runs setup from scratch.
                # This fixes entries that were never loaded or were in a failed state (no sensors).
                old_entry_id = entry.entry_id
                title = f"Mercury NZ - {user_input[CONF_EMAIL]}"
                await self.hass.config_entries.async_remove(old_entry_id)
                _LOGGER.info(
                    "Mercury: removed old entry %s; creating fresh entry so setup runs.",
                    old_entry_id,
                )
                return self.async_create_entry(title=title, data=user_input)

        return self.async_show_form(
            step_id="already_configured_update",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_EMAIL, default=entry.data.get(CONF_EMAIL)
                    ): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            description_placeholders={"email": entry.data.get(CONF_EMAIL, "")},
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Reconfigure existing Mercury entry (e.g. update password)."""
        # Get entry: _get_reconfigure_entry() exists in HA 2024.10+
        if hasattr(self, "_get_reconfigure_entry"):
            entry = self._get_reconfigure_entry()
        else:
            entry_id = self.context.get("entry_id")
            entry = self.hass.config_entries.async_get_entry(entry_id) if entry_id else None

        if not entry:
            return self.async_abort(reason="reconfigure_failed")

        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                ok = await self._validate_mercury(
                    user_input[CONF_EMAIL], user_input[CONF_PASSWORD]
                )
                if not ok:
                    errors["base"] = "cannot_connect"
            except Exception as exc:  # pylint: disable=broad-except
                _LOGGER.error("Unable to connect to Mercury Energy: %s", exc)
                errors["base"] = "cannot_connect"

            if not errors:
                # Update entry and reload integration (data= for compatibility)
                if hasattr(self, "async_update_reload_and_abort"):
                    return self.async_update_reload_and_abort(entry, data=user_input)
                self.hass.config_entries.async_update_entry(entry, data=user_input)
                return self.async_abort(reason="reconfigure_successful")

        schema = vol.Schema(
            {
                vol.Required(CONF_EMAIL, default=entry.data.get(CONF_EMAIL)): str,
                vol.Required(CONF_PASSWORD): str,
            }
        )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=schema,
            errors=errors,
        )
