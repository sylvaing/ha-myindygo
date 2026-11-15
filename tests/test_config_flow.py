"""Tests for the MyIndygo config and options flows."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from homeassistant import config_entries
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.myindygo.api import MyIndygoAuthError, MyIndygoConnectionError
from custom_components.myindygo.const import (
    CONF_CLIENT_ID,
    CONF_LIVE_INTERVAL,
    CONF_PLATFORM_INTERVAL,
    DOMAIN,
)

USER_INPUT = {CONF_EMAIL: " User@Example.com ", CONF_PASSWORD: "secret"}


async def _start(hass: HomeAssistant) -> dict:
    return await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})


async def test_user_flow_creates_entry(hass: HomeAssistant, mock_client: AsyncMock) -> None:
    result = await _start(hass)
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "user@example.com"
    assert result["data"] == {CONF_EMAIL: "user@example.com", CONF_PASSWORD: "secret"}
    assert result["result"].unique_id == "user@example.com"
    mock_client.async_login.assert_awaited_once()


@pytest.mark.parametrize(
    ("side_effect", "modules", "error"),
    [
        (MyIndygoAuthError("bad"), None, "invalid_auth"),
        (MyIndygoConnectionError("down"), None, "cannot_connect"),
        (RuntimeError("boom"), None, "unknown"),
        (None, [], "no_devices"),
    ],
)
async def test_user_flow_errors_then_recover(
    hass: HomeAssistant, mock_client: AsyncMock, side_effect, modules, error
) -> None:
    mock_client.async_login.side_effect = side_effect
    if modules is not None:
        mock_client.async_get_user_with_modules.return_value = {"modules": modules}

    result = await hass.config_entries.flow.async_configure((await _start(hass))["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}

    mock_client.async_login.side_effect = None
    mock_client.async_get_user_with_modules.return_value = {"modules": [{"id": "x"}]}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_already_configured(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_configure((await _start(hass))["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    mock_config_entry.add_to_hass(hass)
    result = await mock_config_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"

    mock_client.async_login.side_effect = MyIndygoAuthError("bad")
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_PASSWORD: "wrong"})
    assert result["errors"] == {"base": "invalid_auth"}

    mock_client.async_login.side_effect = None
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_PASSWORD: "new"})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_config_entry.data[CONF_PASSWORD] == "new"


async def test_options_intervals(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_LIVE_INTERVAL: 3, CONF_PLATFORM_INTERVAL: 20}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options == {CONF_LIVE_INTERVAL: 3, CONF_PLATFORM_INTERVAL: 20}
    mock_client.async_login.assert_not_called()


async def test_options_client_id_validated(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    mock_config_entry.add_to_hass(hass)
    flow_id = (await hass.config_entries.options.async_init(mock_config_entry.entry_id))["flow_id"]
    base = {CONF_LIVE_INTERVAL: 2, CONF_PLATFORM_INTERVAL: 15}

    result = await hass.config_entries.options.async_configure(flow_id, {**base, CONF_CLIENT_ID: "nocolon"})
    assert result["errors"] == {CONF_CLIENT_ID: "invalid_client_id"}

    mock_client.async_login.side_effect = MyIndygoAuthError("bad")
    result = await hass.config_entries.options.async_configure(flow_id, {**base, CONF_CLIENT_ID: "a:b"})
    assert result["errors"] == {"base": "invalid_auth"}

    mock_client.async_login.side_effect = None
    result = await hass.config_entries.options.async_configure(flow_id, {**base, CONF_CLIENT_ID: " a:b "})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options[CONF_CLIENT_ID] == "a:b"
