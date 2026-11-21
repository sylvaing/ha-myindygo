"""Tests for the manual commands of the pool controller outputs (all HTTP calls are mocked)."""

from __future__ import annotations

import copy
import logging
from datetime import timedelta
from typing import Any
from unittest.mock import AsyncMock

import pytest
import voluptuous as vol
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.myindygo.api import MyIndygoAuthError, MyIndygoConnectionError
from custom_components.myindygo.commands import boost, manual_run, pause, program_value, stop
from custom_components.myindygo.const import DOMAIN
from custom_components.myindygo.coordinator import COMMAND_REFRESH_DELAY

from .conftest import DEVICE_PROGRAMS, STATUS

GATEWAY = "10000000AAAAAA0001"
CONTROLLER = "150302BBBBBB0001"


def test_command_bodies() -> None:
    assert manual_run(0, timedelta(hours=1, minutes=30)).body == {
        "index": 0,
        "action": 2,
        "manualDuration": 5400,
    }
    assert boost(0, timedelta(hours=1, minutes=30, seconds=45)).body == {
        "index": 0,
        "action": 3,
        "time": "01:30",
    }
    assert boost(5, timedelta(hours=24)).body["time"] == "24:00"
    assert pause(1, 3).body == {"index": 1, "action": 5, "manualDuration": 3}
    assert stop(2).body == {"index": 2, "action": 1}


def test_program_value_prefers_the_compiled_program() -> None:
    platform = {"programs": [{"index": 0, "programCharacteristics": {"mode": 0}}]}
    assert program_value(0, "mode", DEVICE_PROGRAMS, platform) == 2
    assert program_value(0, "mode", None, platform) == 0
    assert program_value(7, "mode", DEVICE_PROGRAMS, platform) is None


def _status(index: int, **changes: Any) -> dict[str, Any]:
    """A copy of the test status with one output changed."""
    status = copy.deepcopy(STATUS)
    item = next(item for item in status["pool"] if item["index"] == index)
    item.clear()
    item.update({"index": index, "tempRef": 4, **changes})
    return status


@pytest.fixture
async def device_status(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> dict[str, Any]:
    """Set up the entry; the returned dict is what the next status read returns."""
    current = {"status": copy.deepcopy(STATUS)}

    async def device(gateway_serial: str, endpoint: str, child_serial: str | None = None) -> dict:
        if child_serial is None:
            return {"wifiLink": True}
        return current["status"] if endpoint == "status" else DEVICE_PROGRAMS

    mock_client.async_get_device.side_effect = device
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    return current


def _entity_id(hass: HomeAssistant, key: str, platform: str = "binary_sensor") -> str:
    entity_id = er.async_get(hass).async_get_entity_id(platform, DOMAIN, f"{CONTROLLER}_{key}")
    assert entity_id
    return entity_id


async def _call(hass: HomeAssistant, service: str, target: dict[str, Any], **data: Any) -> None:
    await hass.services.async_call(DOMAIN, service, data, target=target, blocking=True)


def _status_reads(client: AsyncMock) -> int:
    return sum(1 for call in client.async_get_device.call_args_list if call.args[1] == "status")


async def _fire_command_refresh(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.tick(timedelta(seconds=COMMAND_REFRESH_DELAY + 1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def test_forced_run_applied(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    device_status: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # The relay answers with the status, the command still waiting for the radio link.
    mock_client.async_send_manual_command.return_value = {**STATUS, "radio": ["cmd"]}
    filtration = _entity_id(hass, "output_0_running")

    await _call(hass, "start_manual_run", {"entity_id": filtration}, duration={"hours": 1, "minutes": 30})

    mock_client.async_send_manual_command.assert_awaited_once_with(
        GATEWAY, CONTROLLER, {"index": 0, "action": 2, "manualDuration": 5400}
    )
    assert hass.states.get(_entity_id(hass, "radio_pending")).state == "on"

    reads = _status_reads(mock_client)
    device_status["status"] = _status(0, value=1, origin=2, time="01:30")
    with caplog.at_level(logging.WARNING):
        await _fire_command_refresh(hass, freezer)
    assert _status_reads(mock_client) == reads + 1
    assert hass.states.get(_entity_id(hass, "output_0_state", "sensor")).state == "manual"
    assert hass.states.get(_entity_id(hass, "radio_pending")).state == "off"
    assert "no visible effect" not in caplog.text


async def test_ignored_command_is_logged(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    device_status: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    mock_client.async_send_manual_command.return_value = STATUS
    device_status["status"] = _status(1, value=0, time="00:00")
    await _call(
        hass, "start_manual_run", {"entity_id": _entity_id(hass, "output_1_running")}, duration="00:30"
    )
    with caplog.at_level(logging.WARNING):
        await _fire_command_refresh(hass, freezer)
    assert "start_manual_run on output 1 had no visible effect" in caplog.text


async def test_radio_still_pending_is_logged(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    device_status: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    mock_client.async_send_manual_command.return_value = {"accepted": True}  # not a status
    device_status["status"] = {**_status(0, value=1, info=["pgm"]), "radio": ["cmd"]}
    await _call(hass, "pause", {"entity_id": _entity_id(hass, "output_0_running")}, days=2)
    mock_client.async_send_manual_command.assert_awaited_once_with(
        GATEWAY, CONTROLLER, {"index": 0, "action": 5, "manualDuration": 2}
    )
    with caplog.at_level(logging.WARNING):
        await _fire_command_refresh(hass, freezer)
    assert "still waiting for the radio link" in caplog.text


async def test_boost_and_stop(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    device_status: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    mock_client.async_send_manual_command.return_value = STATUS
    filtration = {"entity_id": _entity_id(hass, "output_0_running")}

    await _call(hass, "start_boost", filtration, duration={"hours": 2})
    await _call(hass, "stop_manual_command", filtration)

    assert [call.args[2] for call in mock_client.async_send_manual_command.await_args_list] == [
        {"index": 0, "action": 3, "time": "02:00"},
        {"index": 0, "action": 1},
    ]
    # Both commands share one status re-read; the program is running again after the stop.
    reads = _status_reads(mock_client)
    device_status["status"] = _status(0, value=1, info=["pgm"], time="00:46")
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        await _fire_command_refresh(hass, freezer)
    assert _status_reads(mock_client) == reads + 1
    warnings = [
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.WARNING and record.name.startswith("custom_components.myindygo")
    ]
    assert len(warnings) == 1
    assert warnings[0].startswith("start_boost on output 0 had no visible effect")


async def test_output_not_in_auto_mode_is_refused(
    hass: HomeAssistant, mock_client: AsyncMock, device_status: dict[str, Any]
) -> None:
    output_2 = {"entity_id": _entity_id(hass, "output_2_running")}
    for service, data in (("start_manual_run", {"duration": "01:00"}), ("pause", {"days": 1})):
        with pytest.raises(ServiceValidationError) as err:
            await _call(hass, service, output_2, **data)
        assert err.value.translation_key == "output_not_auto"
        assert err.value.translation_placeholders == {"mode": "off"}
    mock_client.async_send_manual_command.assert_not_awaited()

    # Stopping is always allowed (nothing to lose).
    mock_client.async_send_manual_command.return_value = STATUS
    await _call(hass, "stop_manual_command", output_2)
    mock_client.async_send_manual_command.assert_awaited_once()


async def test_boost_refused_on_a_lighting_output(
    hass: HomeAssistant, mock_client: AsyncMock, device_status: dict[str, Any]
) -> None:
    with pytest.raises(ServiceValidationError) as err:
        await _call(
            hass, "start_boost", {"entity_id": _entity_id(hass, "output_1_running")}, duration="01:00"
        )
    assert err.value.translation_key == "boost_not_supported"
    mock_client.async_send_manual_command.assert_not_awaited()


async def test_mode_from_platform_programs_when_compiled_ones_are_missing(
    hass: HomeAssistant, mock_client: AsyncMock, device_status: dict[str, Any], mock_config_entry
) -> None:
    cloud = mock_config_entry.runtime_data.cloud.data
    cloud.device_programs.clear()
    cloud.programs["pc"] = {"programs": [{"index": 0, "programCharacteristics": {"mode": 1}}]}
    with pytest.raises(ServiceValidationError, match="output_not_auto|mode"):
        await _call(
            hass, "start_manual_run", {"entity_id": _entity_id(hass, "output_0_running")}, duration="01:00"
        )

    # Mode unknown: the command is sent, the status re-read will tell.
    cloud.programs.clear()
    mock_client.async_send_manual_command.return_value = STATUS
    await _call(
        hass, "start_manual_run", {"entity_id": _entity_id(hass, "output_0_running")}, duration="01:00"
    )
    mock_client.async_send_manual_command.assert_awaited_once()


async def test_relay_error(
    hass: HomeAssistant, mock_client: AsyncMock, device_status: dict[str, Any]
) -> None:
    mock_client.async_send_manual_command.side_effect = MyIndygoConnectionError(
        "/api/module/x/manual/y: HTTP 504"
    )
    with pytest.raises(HomeAssistantError) as err:
        await _call(hass, "stop_manual_command", {"entity_id": _entity_id(hass, "output_0_running")})
    assert err.value.translation_key == "command_failed"
    assert "HTTP 504" in err.value.translation_placeholders["error"]


async def test_auth_error_starts_reauth(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    device_status: dict[str, Any],
    mock_config_entry: MockConfigEntry,
) -> None:
    mock_client.async_send_manual_command.side_effect = MyIndygoAuthError("denied")
    with pytest.raises(HomeAssistantError) as err:
        await _call(hass, "stop_manual_command", {"entity_id": _entity_id(hass, "output_0_running")})
    assert err.value.translation_key == "auth_failed"
    await hass.async_block_till_done()
    assert any(mock_config_entry.async_get_active_flows(hass, {"reauth"}))


async def test_other_entities_are_not_outputs(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    device_status: dict[str, Any],
    mock_config_entry: MockConfigEntry,
) -> None:
    mock_client.async_send_manual_command.return_value = STATUS
    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, "stop_manual_command", {"entity_id": _entity_id(hass, "radio_pending")})
    assert err.value.translation_key == "not_an_output"
    mock_client.async_send_manual_command.assert_not_awaited()

    # Targeting the controller device reaches its three outputs only.
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, CONTROLLER), mock_config_entry.entry_id
    )
    await _call(hass, "stop_manual_command", {"device_id": device.id})
    assert sorted(
        call.args[2]["index"] for call in mock_client.async_send_manual_command.await_args_list
    ) == [
        0,
        1,
        2,
    ]


@pytest.mark.parametrize(
    ("service", "data"),
    [
        ("start_manual_run", {"duration": "00:00:30"}),
        ("start_manual_run", {"duration": "25:00"}),
        ("start_manual_run", {}),
        ("start_boost", {"duration": "00:00"}),
        ("pause", {"days": 0}),
        ("pause", {"days": 31}),
    ],
)
async def test_invalid_parameters(
    hass: HomeAssistant, mock_client: AsyncMock, device_status: dict[str, Any], service: str, data: dict
) -> None:
    with pytest.raises(vol.Invalid):
        await _call(hass, service, {"entity_id": _entity_id(hass, "output_0_running")}, **data)
    mock_client.async_send_manual_command.assert_not_awaited()


async def test_unload_cancels_the_pending_refresh(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    device_status: dict[str, Any],
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    mock_client.async_send_manual_command.return_value = STATUS
    await _call(hass, "stop_manual_command", {"entity_id": _entity_id(hass, "output_0_running")})
    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    reads = _status_reads(mock_client)
    await _fire_command_refresh(hass, freezer)
    assert _status_reads(mock_client) == reads
