"""Tests for the gateway (LR-MB-10) entities."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.myindygo.api import MyIndygoConnectionError
from custom_components.myindygo.gateway import last_restart

from .conftest import GATEWAY_INFO

SERIAL = "10000000AAAAAA0001"


def _state(hass: HomeAssistant, platform: str, key: str):
    entity_id = er.async_get(hass).async_get_entity_id(platform, "myindygo", f"{SERIAL}_{key}")
    assert entity_id, f"no {platform} entity for {key}"
    return hass.states.get(entity_id)


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def test_last_restart() -> None:
    # 270190 s = 3 days 3 h 3 min 10 s before 2026-11-15 22:38:11 UTC, rounded down to the minute.
    assert last_restart(GATEWAY_INFO) == datetime(2026, 11, 12, 19, 35, tzinfo=UTC)
    assert last_restart({"cdate": "bad", "up": 1}) is None
    assert last_restart(None) is None


async def test_gateway_entities(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    await _setup(hass, mock_config_entry)

    connection = _state(hass, "binary_sensor", "cloud_connection")
    assert connection.state == "on"
    assert connection.name == "LRMB10-AAAAAA Cloud connection"
    assert _state(hass, "binary_sensor", "wifi_link").state == "on"
    assert _state(hass, "sensor", "last_restart").state == "2026-11-12T19:35:00+00:00"

    registry = er.async_get(hass)
    reset = registry.async_get(registry.async_get_entity_id("sensor", "myindygo", f"{SERIAL}_reset_code"))
    assert reset.disabled_by is er.RegistryEntryDisabler.INTEGRATION


async def test_gateway_information_unreachable(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    mock_client.async_get_device.side_effect = MyIndygoConnectionError("gateway offline")
    await _setup(hass, mock_config_entry)

    # The platform still knows the connection state; the relay-based values are unavailable.
    assert _state(hass, "binary_sensor", "cloud_connection").state == "on"
    assert _state(hass, "binary_sensor", "wifi_link").state == STATE_UNAVAILABLE
    assert _state(hass, "sensor", "last_restart").state == STATE_UNAVAILABLE
