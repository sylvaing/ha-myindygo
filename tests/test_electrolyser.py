"""Tests for the electrolyser (IPX PoolTech) entities."""

from __future__ import annotations

from unittest.mock import AsyncMock

from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.myindygo import electrolyser
from custom_components.myindygo.api import MyIndygoConnectionError

from .conftest import MODULES

SERIAL = "FD0001020200112233CCCCCC0001"
IPX = next(module for module in MODULES if module["id"] == "ipx")


def _state(hass: HomeAssistant, platform: str, key: str):
    entity_id = er.async_get(hass).async_get_entity_id(platform, "myindygo", f"{SERIAL}_{key}")
    assert entity_id, f"no {platform} entity for {key}"
    return hass.states.get(entity_id)


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def test_helpers() -> None:
    assert electrolyser.is_pooltech(IPX)
    assert not electrolyser.is_pooltech({"manufacturerType": "FD", "typeIpx": 8})
    assert electrolyser.last_value(IPX, electrolyser.INPUT_PH) == 7.2
    assert electrolyser.last_value(IPX, electrolyser.INPUT_REDOX) is None
    assert electrolyser.output_value(IPX, electrolyser.OUTPUT_ELECTROLYZER, "saltValue") == 3.7
    assert electrolyser.device_state(IPX, "prodStatus") is True
    assert electrolyser.alarms(IPX) == ["Low salt"]


async def test_electrolyser_sensors(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    await _setup(hass, mock_config_entry)

    assert _state(hass, "sensor", "ph").state == "7.2"
    assert _state(hass, "sensor", "ph").name == "IPX-CCCCCC pH"
    assert _state(hass, "sensor", "ph_setpoint").state == "7.2"
    assert _state(hass, "sensor", "ph_regulation_mode").state == "on"
    salt = _state(hass, "sensor", "salt")
    assert salt.state == "3.7"
    assert salt.attributes["unit_of_measurement"] == "g/L"
    assert _state(hass, "sensor", "production_setpoint").state == "10"
    assert _state(hass, "sensor", "electrolysis_mode").state == "percentage"
    assert _state(hass, "sensor", "boost_remaining").state == "0"
    assert _state(hass, "sensor", "electrolysis_hours").state == "2331"
    assert _state(hass, "sensor", "cell_voltage").state == "23"
    assert _state(hass, "sensor", "last_report").state == "2026-11-14T14:01:07+00:00"
    # No redox probe on this installation: no entity.
    assert not er.async_get(hass).async_get_entity_id("sensor", "myindygo", f"{SERIAL}_redox")


async def test_electrolyser_binary_sensors(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    await _setup(hass, mock_config_entry)

    assert _state(hass, "binary_sensor", "production").state == "on"
    assert _state(hass, "binary_sensor", "ph_injection").state == "on"
    assert _state(hass, "binary_sensor", "boost").state == "off"
    assert _state(hass, "binary_sensor", "wintering").state == "off"
    alarm = _state(hass, "binary_sensor", "alarm")
    assert alarm.state == "on"
    assert alarm.attributes["alarms"] == ["Low salt"]

    registry = er.async_get(hass)
    flow = registry.async_get(
        registry.async_get_entity_id("binary_sensor", "myindygo", f"{SERIAL}_flow_input")
    )
    assert flow.disabled_by is er.RegistryEntryDisabler.INTEGRATION


async def test_electrolyser_unavailable_when_cloud_fails(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    await _setup(hass, mock_config_entry)
    mock_client.async_get_user_with_modules.side_effect = MyIndygoConnectionError("down")
    await mock_config_entry.runtime_data.cloud.async_refresh()
    await hass.async_block_till_done()

    assert _state(hass, "sensor", "ph").state == STATE_UNAVAILABLE
