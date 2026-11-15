"""Config flow for the MyIndygo (Solem) integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD

from .const import DOMAIN

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


class MyIndygoConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for MyIndygo."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the MyIndygo account credentials."""
        if user_input is not None:
            email = user_input[CONF_EMAIL].strip().lower()
            await self.async_set_unique_id(email)
            self._abort_if_unique_id_configured()
            # TODO(#2): validate the credentials against the MyIndygo cloud API.
            return self.async_create_entry(title=email, data={**user_input, CONF_EMAIL: email})

        return self.async_show_form(step_id="user", data_schema=STEP_USER_DATA_SCHEMA)
