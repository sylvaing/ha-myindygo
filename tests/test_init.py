"""Tests for the MyIndygo entry set-up."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.myindygo.api import MyIndygoAuthError, MyIndygoConnectionError
from custom_components.myindygo.const import DOMAIN


async def test_setup_registers_device_tree(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    assert mock_config_entry.state is ConfigEntryState.LOADED

    registry = dr.async_get(hass)
    entry_id = mock_config_entry.entry_id
    gateway = registry.async_get_device_by_identifier((DOMAIN, "10000000AAAAAA0001"), entry_id)
    controller = registry.async_get_device_by_identifier((DOMAIN, "150302BBBBBB0001"), entry_id)
    ipx = registry.async_get_device_by_identifier((DOMAIN, "FD0001020200112233CCCCCC0001"), entry_id)
    assert gateway.model == "LR-MB-10" and gateway.manufacturer == "Solem" and gateway.via_device_id is None
    assert controller.model == "LR-PC" and controller.via_device_id == gateway.id
    assert ipx.model == "IPX" and ipx.via_device_id == controller.id

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED


@pytest.mark.parametrize(
    ("error", "state"),
    [
        (MyIndygoAuthError("bad"), ConfigEntryState.SETUP_ERROR),
        (MyIndygoConnectionError("down"), ConfigEntryState.SETUP_RETRY),
    ],
)
async def test_setup_errors(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry, error, state
) -> None:
    mock_client.async_get_user_with_modules.side_effect = error
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    assert mock_config_entry.state is state
    if isinstance(error, MyIndygoAuthError):
        assert any(mock_config_entry.async_get_active_flows(hass, {"reauth"}))
