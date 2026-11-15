"""Tests for the pool controller entities."""

from __future__ import annotations

from unittest.mock import AsyncMock

from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import STATE_UNAVAILABLE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.myindygo.api import MyIndygoConnectionError

SERIAL = "150302BBBBBB0001"


def _state(hass: HomeAssistant, platform: str, key: str):
    entity_id = er.async_get(hass).async_get_entity_id(platform, "myindygo", f"{SERIAL}_{key}")
    assert entity_id, f"no {platform} entity for {key}"
    return hass.states.get(entity_id)


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_controller_sensors(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    freezer.move_to("2026-11-16 12:00:00+00:00")
    await _setup(hass, mock_config_entry)

    temperature = _state(hass, "sensor", "water_temperature")
    assert temperature.state == "19.29"
    assert temperature.attributes["unit_of_measurement"] == "°C"
    assert temperature.name == "LRPC-BBBBBB Water temperature"

    assert _state(hass, "sensor", "output_0_state").state == "program"
    assert _state(hass, "sensor", "output_1_state").state == "manual"
    assert _state(hass, "sensor", "output_2_state").state == "off"
    assert _state(hass, "sensor", "output_0_remaining").state == "46"
    assert _state(hass, "sensor", "output_1_remaining").state == "90"
    assert _state(hass, "sensor", "output_0_mode").state == "auto"
    assert _state(hass, "sensor", "output_2_mode").state == "off"
    assert _state(hass, "sensor", "output_0_rule").state == "temperature"
    assert _state(hass, "sensor", "output_1_type").state == "lighting"
    assert _state(hass, "sensor", "temperature_band").state == "16-18 °C"
    planned = _state(hass, "sensor", "filtration_planned_today")
    assert float(planned.state) == 5.0
    assert planned.attributes["unit_of_measurement"] == "h"
    assert _state(hass, "sensor", "last_communication").state == "2026-11-14T14:14:47+00:00"
    assert _state(hass, "sensor", "output_1_state").name == "LRPC-BBBBBB Output 1 state"

    # Diagnostic and disabled by default: meaning of the value not confirmed yet.
    registry = er.async_get(hass)
    entry = registry.async_get(
        registry.async_get_entity_id("sensor", "myindygo", f"{SERIAL}_controller_temperature")
    )
    assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert entry.entity_category is EntityCategory.DIAGNOSTIC


async def test_controller_binary_sensors(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    await _setup(hass, mock_config_entry)

    assert _state(hass, "binary_sensor", "output_0_running").state == "on"
    assert _state(hass, "binary_sensor", "output_0_running").name == "LRPC-BBBBBB Filtration"
    assert _state(hass, "binary_sensor", "output_2_running").state == "off"
    assert _state(hass, "binary_sensor", "radio_pending").state == "off"
    assert _state(hass, "binary_sensor", "input_alert").state == "off"


async def test_gateway_offline_makes_live_entities_unavailable(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    mock_client.async_get_device.side_effect = MyIndygoConnectionError("gateway offline")
    await _setup(hass, mock_config_entry)

    assert _state(hass, "sensor", "water_temperature").state == STATE_UNAVAILABLE
    assert _state(hass, "binary_sensor", "output_0_running").state == STATE_UNAVAILABLE
