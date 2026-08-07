"""Config flow for Mercury Energy NZ integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN, CONF_EMAIL, CONF_ICP
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
    # MINOR_VERSION 2 (v2.0.0): added _primary_service_id to entry.data (additive,
    # backward-compatible — v1.5.x ignores the new field). Bumping minor (not major)
    # keeps HA downgrades from failing setup. See HA blog 2023-12-18 minor-version.
    MINOR_VERSION = 2

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> "MercuryOptionsFlow":
        """Return the options flow (pin a single ICP for this instance)."""
        return MercuryOptionsFlow()

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


# Sentinel for "no pin" — vol.In cannot express None as a form value, so the
# empty string is the wire form and is normalised back to None on submit.
ALL_ICPS = ""


def _icp_label(service: Any) -> str:
    """Human-readable choice label: address when Mercury gives us one."""
    address = getattr(service, "address", None)
    return f"{service.service_id} — {address}" if address else str(service.service_id)


class MercuryOptionsFlow(config_entries.OptionsFlow):
    """Options: pin a single electricity ICP for this HA instance (#30).

    Deliberately no ``__init__``: ``self.config_entry`` is supplied by the base
    class, and assigning it manually is deprecated since HA 2024.11 (this
    integration's min_ha_version is 2025.11.0).
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Show/handle the ICP selector."""
        if user_input is not None:
            # ALL_ICPS ⇒ clear the pin and go back to the default multi-ICP view.
            return self.async_create_entry(
                title="", data={CONF_ICP: user_input.get(CONF_ICP) or None}
            )

        # Choices come from the live coordinator's first-cycle discovery.
        coordinator = self.hass.data.get(DOMAIN, {}).get(self.config_entry.entry_id)
        services = getattr(coordinator, "_discovered_electricity_services", None) or []
        if not services:
            return self.async_abort(reason="icps_not_discovered")

        choices = {ALL_ICPS: "All ICPs (default)"}
        choices.update({s.service_id: _icp_label(s) for s in services})

        current = self.config_entry.options.get(CONF_ICP) or ALL_ICPS
        if current not in choices:
            # Pinned ICP is no longer on the account — the coordinator already
            # warned and fell back to all ICPs; reflect that in the form.
            current = ALL_ICPS

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {vol.Optional(CONF_ICP, default=current): vol.In(choices)}
            ),
        )
