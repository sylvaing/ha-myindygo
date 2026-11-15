"""Config flow for the MyIndygo (Solem) integration."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlowWithReload
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import MyIndygoApiClient, MyIndygoAuthError, MyIndygoConnectionError
from .const import (
    CONF_CLIENT_ID,
    CONF_LIVE_INTERVAL,
    CONF_PLATFORM_INTERVAL,
    DEFAULT_LIVE_INTERVAL,
    DEFAULT_PLATFORM_INTERVAL,
    DOMAIN,
    MAX_LIVE_INTERVAL,
    MAX_PLATFORM_INTERVAL,
    MIN_LIVE_INTERVAL,
    MIN_PLATFORM_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): TextSelector(TextSelectorConfig(type=TextSelectorType.EMAIL)),
        vol.Required(CONF_PASSWORD): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD)),
    }
)
STEP_REAUTH_DATA_SCHEMA = vol.Schema(
    {vol.Required(CONF_PASSWORD): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))}
)


async def async_validate_account(
    hass: HomeAssistant, email: str, password: str, client_id: str | None = None
) -> dict[str, str]:
    """Log in and read the account's modules. Return form errors (empty when valid)."""
    client = MyIndygoApiClient(async_get_clientsession(hass), email, password, client_id=client_id)
    try:
        await client.async_login()
        user = await client.async_get_user_with_modules()
    except MyIndygoAuthError:
        return {"base": "invalid_auth"}
    except MyIndygoConnectionError:
        return {"base": "cannot_connect"}
    except Exception:
        _LOGGER.exception("Unexpected error while validating the MyIndygo account")
        return {"base": "unknown"}
    if not user.get("modules"):
        return {"base": "no_devices"}
    return {}


class MyIndygoConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for MyIndygo."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> MyIndygoOptionsFlow:
        """Return the options flow."""
        return MyIndygoOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the MyIndygo account credentials."""
        errors: dict[str, str] = {}
        if user_input is not None:
            email = user_input[CONF_EMAIL].strip().lower()
            await self.async_set_unique_id(email)
            self._abort_if_unique_id_configured()
            errors = await async_validate_account(self.hass, email, user_input[CONF_PASSWORD])
            if not errors:
                return self.async_create_entry(
                    title=email, data={CONF_EMAIL: email, CONF_PASSWORD: user_input[CONF_PASSWORD]}
                )

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(STEP_USER_DATA_SCHEMA, user_input),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Start reauthentication when the stored password is rejected."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the new password."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = await async_validate_account(
                self.hass,
                entry.data[CONF_EMAIL],
                user_input[CONF_PASSWORD],
                entry.options.get(CONF_CLIENT_ID),
            )
            if not errors:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]}
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_REAUTH_DATA_SCHEMA,
            description_placeholders={"email": entry.data[CONF_EMAIL]},
            errors=errors,
        )


class MyIndygoOptionsFlow(OptionsFlowWithReload):
    """Options: polling intervals and, for advanced users, the app client identifier."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Manage the options."""
        errors: dict[str, str] = {}
        if user_input is not None:
            options = dict(user_input)
            client_id = (options.pop(CONF_CLIENT_ID, None) or "").strip()
            if client_id:
                if ":" not in client_id:
                    errors[CONF_CLIENT_ID] = "invalid_client_id"
                else:
                    entry = self.config_entry
                    errors = await async_validate_account(
                        self.hass, entry.data[CONF_EMAIL], entry.data[CONF_PASSWORD], client_id
                    )
                options[CONF_CLIENT_ID] = client_id
            for key in (CONF_LIVE_INTERVAL, CONF_PLATFORM_INTERVAL):
                options[key] = int(options[key])
            if not errors:
                return self.async_create_entry(data=options)

        current = user_input or self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_LIVE_INTERVAL, default=current.get(CONF_LIVE_INTERVAL, DEFAULT_LIVE_INTERVAL)
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_LIVE_INTERVAL,
                        max=MAX_LIVE_INTERVAL,
                        step=1,
                        unit_of_measurement="min",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_PLATFORM_INTERVAL,
                    default=current.get(CONF_PLATFORM_INTERVAL, DEFAULT_PLATFORM_INTERVAL),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_PLATFORM_INTERVAL,
                        max=MAX_PLATFORM_INTERVAL,
                        step=1,
                        unit_of_measurement="min",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Optional(
                    CONF_CLIENT_ID, description={"suggested_value": current.get(CONF_CLIENT_ID, "")}
                ): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD)),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
