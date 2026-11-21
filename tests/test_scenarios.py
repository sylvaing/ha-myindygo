"""End-to-end tests on anonymised copies of real API answers (see tools/anonymize_captures.py).

* ``filtration_running``: 14 Nov 2026, afternoon, filtration running on its thermo-adaptive
  schedule, electrolyser producing at 10 %.
* ``electrolyser_stopped``: 21 Nov 2026, electrolysis and pH regulation switched off for the
  winter by the owner; the electrolyser keeps reporting a meaningless pH.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

FIXTURES = Path(__file__).parent / "fixtures"
GATEWAY = "100000AAAAAA0001"
CONTROLLER = "150302BBBBBB0001"
IPX = "FD00010000000000CCCCCC0001"


def load(scenario: str) -> dict:
    return {path.stem: json.loads(path.read_text()) for path in (FIXTURES / scenario).glob("*.json")}


def use_scenario(client: AsyncMock, scenario: str) -> None:
    data = load(scenario)
    client.async_get_user_with_modules.side_effect = None
    client.async_get_user_with_modules.return_value = data["user_with_modules"]
    client.async_get_pools.return_value = data["pools"]
    client.async_get_pool_status.return_value = data["pool_status"]
    client.async_get_programs.return_value = data["controller_programs"]

    async def device(gateway_serial: str, endpoint: str, child_serial: str | None = None) -> dict:
        assert gateway_serial == GATEWAY
        if child_serial is None:
            return {"information": data["gateway_information"]}[endpoint]
        assert child_serial == CONTROLLER
        return {"status": data["device_status"], "programs": data["device_programs"]}[endpoint]

    client.async_get_device.side_effect = device


def states(hass: HomeAssistant, serial: str) -> dict[str, str]:
    """State of every entity of a device, keyed by the part of the unique id after the serial."""
    registry = er.async_get(hass)
    result = {}
    for entry in registry.entities.values():
        if entry.platform == "myindygo" and entry.unique_id.startswith(f"{serial}_"):
            state = hass.states.get(entry.entity_id)
            if state is not None:
                result[entry.unique_id.removeprefix(f"{serial}_")] = state.state
    return result


async def _setup(hass: HomeAssistant, client: AsyncMock, entry: MockConfigEntry, scenario: str) -> None:
    use_scenario(client, scenario)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_filtration_running(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    freezer.move_to("2026-11-14 14:20:00+00:00")
    await _setup(hass, mock_client, mock_config_entry, "filtration_running")

    controller = states(hass, CONTROLLER)
    assert controller["water_temperature"] == "19.29"
    assert controller["output_0_running"] == "on"
    assert controller["output_0_state"] == "program"
    assert controller["output_0_remaining"] == "46"
    assert controller["output_0_mode"] == "auto"
    assert controller["output_0_rule"] == "temperature"
    assert controller["temperature_band"] == "16-18 °C"
    assert float(controller["filtration_planned_today"]) == 5.0
    assert controller["output_1_type"] == "lighting"
    assert controller["output_1_mode"] == "off"
    assert controller["output_2_running"] == "off"

    ipx = states(hass, IPX)
    assert ipx["ph"] == "7.2"
    assert ipx["ph_setpoint"] == "7.2"
    assert ipx["ph_regulation_mode"] == "on"
    assert ipx["salt"] == "3.7"
    assert ipx["production_setpoint"] == "10"
    assert ipx["electrolysis_mode"] == "percentage"
    assert ipx["production"] == "on"
    assert ipx["alarm"] == "off"
    assert ipx["cell_voltage"] == "23"
    assert "redox" not in ipx

    gateway = states(hass, GATEWAY)
    assert gateway["cloud_connection"] == "on"
    assert gateway["wifi_link"] == "on"
    # 153885 s before 2026-11-14 14:15:17 UTC, rounded down to the minute.
    assert gateway["last_restart"] == "2026-11-12T19:30:00+00:00"


async def test_electrolyser_stopped_for_winter(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    freezer.move_to("2026-11-21 16:05:00+00:00")
    await _setup(hass, mock_client, mock_config_entry, "electrolyser_stopped")

    ipx = states(hass, IPX)
    assert ipx["electrolysis_mode"] == "off"
    assert ipx["ph_regulation_mode"] == "off"
    assert ipx["production"] == "off"
    # The platform keeps reporting a pH value while the electrolyser is stopped.
    assert ipx["ph"] == "1.6"
    assert ipx["last_report"] == "2026-11-21T02:55:50+00:00"

    controller = states(hass, CONTROLLER)
    assert controller["water_temperature"] == "17.57"
    assert controller["output_0_running"] == "on"
    assert controller["temperature_band"] == "16-18 °C"


@pytest.mark.parametrize("scenario", ["filtration_running", "electrolyser_stopped"])
async def test_no_entity_unavailable(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry, scenario: str
) -> None:
    await _setup(hass, mock_client, mock_config_entry, scenario)
    all_states = {**states(hass, CONTROLLER), **states(hass, IPX), **states(hass, GATEWAY)}
    assert len(all_states) == 50
    assert [key for key, value in all_states.items() if value == "unavailable"] == []
