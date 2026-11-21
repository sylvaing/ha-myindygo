"""Tests for the program writes: output mode and daily filtration adjustment (all HTTP calls are mocked)."""

from __future__ import annotations

import copy
import logging
from datetime import timedelta
from typing import Any
from unittest.mock import AsyncMock

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.myindygo.api import MyIndygoAuthError, MyIndygoConnectionError
from custom_components.myindygo.const import DOMAIN
from custom_components.myindygo.programs import (
    PROGRAM_REFRESH_DELAY,
    ProgramError,
    build_program_change,
    compile_temperature_sched,
    device_payload,
    platform_payload,
)

from .test_api import TOKEN, FakeSession, make_client
from .test_scenarios import CONTROLLER, GATEWAY, load, use_scenario

SCENARIO = load("filtration_running")
PLATFORM = SCENARIO["controller_programs"]
DEVICE = SCENARIO["device_programs"]
MODULE_ID = "000000000000000000000003"


def _program(payload: dict[str, Any], index: int) -> dict[str, Any]:
    return next(p for p in payload["programs"] if p["index"] == index)


# Pure helpers ---------------------------------------------------------------------------------


def test_compile_matches_the_real_controller() -> None:
    """The thermo-adaptive schedule of the platform compiles to the matrix read from the controller."""
    filtration = _program(PLATFORM, 0)
    assert filtration["programCharacteristics"]["adaptOffset"] == -60
    assert compile_temperature_sched(filtration, -60) == _program(DEVICE, 0)["sched"]


def test_compile_shifts_and_clamps_the_level() -> None:
    filtration = _program(PLATFORM, 0)
    standard = compile_temperature_sched(filtration, 0)
    # Band 0 uses level 0 (05-06 and 22-23), band 1 level 1 (12-15) without offset.
    assert standard[0][0] == (1 << 5) | (1 << 22)
    assert standard[0][1] == 0b111 << 12
    # Clamped to the first and last levels.
    assert compile_temperature_sched(filtration, -240)[0][0] == standard[0][0]
    assert compile_temperature_sched(filtration, 240)[0][11] == standard[0][11]
    # No schedule for a day: empty row.
    weekend_only = {
        **filtration,
        "temperatureSchedules": [{**filtration["temperatureSchedules"][0], "days": 96}],
    }
    matrix = compile_temperature_sched(weekend_only, 0)
    assert matrix[0] == [0] * 12
    assert matrix[6] == standard[6]


def test_compile_ranges_spanning_midnight() -> None:
    program = {
        "temperatureSchedules": [{"days": 1, "indexes": [0], "thresholds": [[{"start": 1380, "end": 60}]]}]
    }
    assert compile_temperature_sched(program, 0)[0][0] == (1 << 23) | 1


def test_platform_payload_keeps_editable_fields_only() -> None:
    program = copy.deepcopy(_program(PLATFORM, 0))
    program["windows"][0] = {"start": 600, "end": 720, "runningDays": 127}
    payload = platform_payload(program)
    assert payload["windows"] == [{"start": 600, "end": 720, "runningDays": 127}]
    assert payload["id"] == program["id"]
    assert payload["programCharacteristics"] == program["programCharacteristics"]
    assert payload["temperatureSchedules"] == program["temperatureSchedules"]
    assert payload["temperatureHysteresis"] is None
    for read_only in ("createdAt", "updatedAt", "module", "dataChanged", "sentAt"):
        assert read_only not in payload


def test_device_payload() -> None:
    program = _program(DEVICE, 1)
    assert device_payload(program) == {
        "index": 1,
        "name": "",
        "programCharacteristics": program["programCharacteristics"],
        "sched": program["sched"],
    }


def test_mode_change_preserves_everything_else() -> None:
    change = build_program_change(PLATFORM, DEVICE, 2, mode=1)
    assert change is not None
    platform, device = change
    for index in (0, 1, 2):
        new_platform, old_platform = copy.deepcopy(platform[index]), _program(PLATFORM, index)
        new_device, old_device = copy.deepcopy(device[index]), _program(DEVICE, index)
        if index == 2:
            assert new_platform["programCharacteristics"].pop("mode") == 1
            assert new_device["programCharacteristics"].pop("mode") == 1
            old_platform = copy.deepcopy(old_platform)
            old_device = copy.deepcopy(old_device)
            old_platform["programCharacteristics"].pop("mode")
            old_device["programCharacteristics"].pop("mode")
        assert new_platform == old_platform
        assert new_device == old_device
    # The copies read are not modified.
    assert _program(DEVICE, 2)["programCharacteristics"]["mode"] == 0


def test_no_change_when_already_set() -> None:
    assert build_program_change(PLATFORM, DEVICE, 0, mode=2) is None
    assert build_program_change(PLATFORM, DEVICE, 0, adapt_offset=-60) is None


def test_daily_adjustment_recompiles_the_filtration_only() -> None:
    change = build_program_change(PLATFORM, DEVICE, 0, adapt_offset=60)
    assert change is not None
    platform, device = change
    assert platform[0]["programCharacteristics"]["adaptOffset"] == 60
    assert device[0]["sched"] == compile_temperature_sched(_program(PLATFORM, 0), 60)
    assert device[0]["sched"] != _program(DEVICE, 0)["sched"]
    assert device[0]["programCharacteristics"] == _program(DEVICE, 0)["programCharacteristics"]
    assert platform[1:] == PLATFORM["programs"][1:]
    assert device[1:] == DEVICE["programs"][1:]


def test_daily_adjustment_refused_when_the_schedules_differ() -> None:
    device = copy.deepcopy(DEVICE)
    device["programs"][0]["sched"][3][4] = 0
    with pytest.raises(ProgramError) as err:
        build_program_change(PLATFORM, device, 0, adapt_offset=0)
    assert err.value.key == "program_sched_mismatch"


def test_daily_adjustment_refused_on_other_programs() -> None:
    with pytest.raises(ProgramError) as err:
        build_program_change(PLATFORM, DEVICE, 1, adapt_offset=0)
    assert err.value.key == "daily_adjustment_not_supported"


@pytest.mark.parametrize(
    ("platform", "device"),
    [
        ({"programs": PLATFORM["programs"][:2]}, DEVICE),
        (PLATFORM, {"programs": []}),
        (PLATFORM, {"programs": [{**p, "index": p["index"] + 1} for p in DEVICE["programs"]]}),
    ],
)
def test_copies_must_match(platform: dict[str, Any], device: dict[str, Any]) -> None:
    with pytest.raises(ProgramError) as err:
        build_program_change(platform, device, 0, mode=0)
    assert err.value.key == "program_copies_differ"


def test_unknown_output() -> None:
    with pytest.raises(ProgramError):
        build_program_change(PLATFORM, DEVICE, 5, mode=0)


# API client -----------------------------------------------------------------------------------

PROGRAMS_PATH = "/api/module/10000007ABCD0001/programs/ABCDEF"


async def test_api_write_sequence_bodies() -> None:
    session = FakeSession()
    session.add("POST", "/oauth2/token", payload=TOKEN)
    session.add("PUT", "/api/updatePrograms", payload={"ok": True})
    session.add("POST", PROGRAMS_PATH, payload={"programs": []})
    session.add("POST", "/api/reportProgramsDatasSent", payload={})
    client = make_client(session)

    await client.async_update_programs("m1", [{"id": "p0", "index": 0}])
    await client.async_write_device_programs("10000007ABCD0001", "150302ABCDEF0001", [{"index": 0}])
    await client.async_report_programs_sent("m1", ["p0"])

    put, relay, report = session.calls[1:]
    assert put["method"] == "PUT"
    assert put["json"] == {"module": "m1", "programmationType": 1, "programs": [{"id": "p0", "index": 0}]}
    assert relay["json"] == {"programs": [{"index": 0}]}
    assert "T" in relay["headers"]["Date"]
    assert report["json"] == {"module": "m1", "programs": ["p0"]}


async def test_api_write_relogin_once() -> None:
    session = FakeSession()
    session.add("POST", "/oauth2/token", payload=TOKEN)
    session.add("PUT", "/api/updatePrograms", status=401, payload=None)
    session.add("POST", "/oauth2/token", payload={**TOKEN, "access_token": "new"})
    session.add("PUT", "/api/updatePrograms", payload={})
    client = make_client(session)

    await client.async_update_programs("m1", [])
    assert session.calls[-1]["headers"]["Authorization"] == "Bearer new"


async def test_api_relay_write_error() -> None:
    session = FakeSession()
    session.add("POST", "/oauth2/token", payload=TOKEN)
    session.add("POST", PROGRAMS_PATH, payload={"error": {"code": "module_offline"}})
    with pytest.raises(MyIndygoConnectionError):
        await make_client(session).async_write_device_programs("10000007ABCD0001", "150302ABCDEF0001", [])


# Home Assistant entities ----------------------------------------------------------------------


@pytest.fixture
async def programs(hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry) -> dict:
    """Set up the entry on the real-data scenario; the returned dict is what the next reads return."""
    use_scenario(mock_client, "filtration_running")
    current = {"platform": copy.deepcopy(PLATFORM), "device": copy.deepcopy(DEVICE)}
    previous_device = mock_client.async_get_device.side_effect

    async def device(gateway_serial: str, endpoint: str, child_serial: str | None = None) -> dict:
        if endpoint == "programs":
            return copy.deepcopy(current["device"])
        return await previous_device(gateway_serial, endpoint, child_serial)

    async def platform(module_id: str) -> dict:
        assert module_id == MODULE_ID
        return copy.deepcopy(current["platform"])

    mock_client.async_get_device.side_effect = device
    mock_client.async_get_programs.side_effect = platform
    mock_client.async_update_programs.return_value = {}
    mock_client.async_write_device_programs.return_value = {}
    mock_client.async_report_programs_sent.return_value = {}
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    return current


def _entity_id(hass: HomeAssistant, key: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id("select", DOMAIN, f"{CONTROLLER}_{key}")
    assert entity_id
    return entity_id


async def _select(hass: HomeAssistant, key: str, option: str) -> None:
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": _entity_id(hass, key), "option": option},
        blocking=True,
    )


def _writes(client: AsyncMock) -> list[str]:
    names = ("async_update_programs", "async_write_device_programs", "async_report_programs_sent")
    return [call[0] for call in client.mock_calls if call[0] in names]


async def test_entities(hass: HomeAssistant, programs: dict) -> None:
    assert hass.states.get(_entity_id(hass, "output_0_program_mode")).state == "auto"
    assert hass.states.get(_entity_id(hass, "output_1_program_mode")).state == "off"
    state = hass.states.get(_entity_id(hass, "filtration_daily_adjustment"))
    assert state.state == "minus_1"
    assert state.attributes["options"][0] == "minus_4"
    assert state.attributes["options"][-1] == "plus_4"


async def test_mode_write_sequence(hass: HomeAssistant, mock_client: AsyncMock, programs: dict) -> None:
    await _select(hass, "output_2_program_mode", "on")

    assert _writes(mock_client) == [
        "async_update_programs",
        "async_write_device_programs",
        "async_report_programs_sent",
    ]
    module_id, sent_platform = mock_client.async_update_programs.call_args.args
    assert module_id == MODULE_ID
    expected_platform = [platform_payload(p) for p in copy.deepcopy(PLATFORM["programs"])]
    expected_platform[2]["programCharacteristics"]["mode"] = 1
    assert sent_platform == expected_platform

    gateway, controller, sent_device = mock_client.async_write_device_programs.call_args.args
    assert (gateway, controller) == (GATEWAY, CONTROLLER)
    expected_device = [device_payload(p) for p in copy.deepcopy(DEVICE["programs"])]
    expected_device[2]["programCharacteristics"]["mode"] = 1
    assert sent_device == expected_device

    mock_client.async_report_programs_sent.assert_awaited_once_with(
        MODULE_ID, [p["id"] for p in PLATFORM["programs"]]
    )
    # Shown at once, before the delayed re-read.
    assert hass.states.get(_entity_id(hass, "output_2_program_mode")).state == "on"


async def test_mode_already_set(hass: HomeAssistant, mock_client: AsyncMock, programs: dict) -> None:
    await _select(hass, "output_0_program_mode", "auto")
    assert _writes(mock_client) == []


async def test_read_failure(hass: HomeAssistant, mock_client: AsyncMock, programs: dict) -> None:
    mock_client.async_get_programs.side_effect = MyIndygoConnectionError("timeout")
    with pytest.raises(HomeAssistantError) as err:
        await _select(hass, "output_2_program_mode", "on")
    assert err.value.translation_key == "program_read_failed"
    assert _writes(mock_client) == []


async def test_platform_save_failure(hass: HomeAssistant, mock_client: AsyncMock, programs: dict) -> None:
    mock_client.async_update_programs.side_effect = MyIndygoConnectionError("HTTP 500")
    with pytest.raises(HomeAssistantError) as err:
        await _select(hass, "output_2_program_mode", "on")
    assert err.value.translation_key == "program_save_failed"
    assert _writes(mock_client) == ["async_update_programs"]
    assert hass.states.get(_entity_id(hass, "output_2_program_mode")).state == "off"


async def test_controller_send_failure(hass: HomeAssistant, mock_client: AsyncMock, programs: dict) -> None:
    mock_client.async_write_device_programs.side_effect = MyIndygoConnectionError("module_offline")
    with pytest.raises(HomeAssistantError) as err:
        await _select(hass, "output_2_program_mode", "on")
    assert err.value.translation_key == "program_send_failed"
    # The platform has the new mode, the controller keeps the old one: nothing is reported.
    assert _writes(mock_client) == ["async_update_programs", "async_write_device_programs"]
    assert hass.states.get(_entity_id(hass, "output_2_program_mode")).state == "off"


async def test_report_failure_is_not_fatal(
    hass: HomeAssistant, mock_client: AsyncMock, programs: dict, caplog: pytest.LogCaptureFixture
) -> None:
    mock_client.async_report_programs_sent.side_effect = MyIndygoConnectionError("HTTP 502")
    with caplog.at_level(logging.WARNING):
        await _select(hass, "output_2_program_mode", "on")
    assert len(_writes(mock_client)) == 3
    assert hass.states.get(_entity_id(hass, "output_2_program_mode")).state == "on"
    assert "report to the platform failed" in caplog.text


async def test_auth_failure_starts_reauth(
    hass: HomeAssistant, mock_client: AsyncMock, programs: dict, mock_config_entry: MockConfigEntry
) -> None:
    mock_client.async_update_programs.side_effect = MyIndygoAuthError("denied")
    with pytest.raises(HomeAssistantError) as err:
        await _select(hass, "output_2_program_mode", "on")
    assert err.value.translation_key == "auth_failed"
    await hass.async_block_till_done()
    assert any(mock_config_entry.async_get_active_flows(hass, {"reauth"}))
    assert _writes(mock_client) == ["async_update_programs"]


async def test_daily_adjustment_write(hass: HomeAssistant, mock_client: AsyncMock, programs: dict) -> None:
    await _select(hass, "filtration_daily_adjustment", "plus_2")

    sent_platform = mock_client.async_update_programs.call_args.args[1]
    assert sent_platform[0]["programCharacteristics"]["adaptOffset"] == 120
    assert sent_platform[1:] == [platform_payload(p) for p in PLATFORM["programs"][1:]]
    sent_device = mock_client.async_write_device_programs.call_args.args[2]
    assert sent_device[0]["sched"] == compile_temperature_sched(_program(PLATFORM, 0), 120)
    assert sent_device[0]["programCharacteristics"] == _program(DEVICE, 0)["programCharacteristics"]
    assert sent_device[1:] == [device_payload(p) for p in DEVICE["programs"][1:]]
    assert hass.states.get(_entity_id(hass, "filtration_daily_adjustment")).state == "plus_2"


async def test_daily_adjustment_refused_on_mismatch(
    hass: HomeAssistant, mock_client: AsyncMock, programs: dict
) -> None:
    programs["device"]["programs"][0]["sched"][0][0] = 1
    with pytest.raises(ServiceValidationError) as err:
        await _select(hass, "filtration_daily_adjustment", "standard")
    assert err.value.translation_key == "program_sched_mismatch"
    assert _writes(mock_client) == []


async def test_daily_adjustment_unavailable_with_time_rule(
    hass: HomeAssistant, mock_client: AsyncMock, programs: dict
) -> None:
    programs["device"]["programs"][0]["programCharacteristics"]["rule"] = 0
    await hass.config_entries.async_reload(next(iter(hass.config_entries.async_entries(DOMAIN))).entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(_entity_id(hass, "filtration_daily_adjustment")).state == "unavailable"


async def test_delayed_refresh_warns_when_not_applied(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    programs: dict,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await _select(hass, "output_2_program_mode", "on")
    # The controller still reports the old programs.
    freezer.tick(timedelta(seconds=PROGRAM_REFRESH_DELAY + 1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert "do not show the change of output 2" in caplog.text
    assert hass.states.get(_entity_id(hass, "output_2_program_mode")).state == "off"


async def test_delayed_refresh_applied(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    programs: dict,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await _select(hass, "output_2_program_mode", "on")
    programs["device"]["programs"][2]["programCharacteristics"]["mode"] = 1
    freezer.tick(timedelta(seconds=PROGRAM_REFRESH_DELAY + 1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert "do not show" not in caplog.text
    assert hass.states.get(_entity_id(hass, "output_2_program_mode")).state == "on"
