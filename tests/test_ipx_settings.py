"""Tests for the electrolyser settings (number, select, button); every HTTP call is mocked."""

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
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.myindygo import ipx_settings
from custom_components.myindygo.api import MyIndygoAuthError, MyIndygoConnectionError

from .conftest import DEVICE_PROGRAMS, MODULES, STATUS
from .test_api import TOKEN, FakeSession, make_client

SERIAL = "FD0001020200112233CCCCCC0001"


def _ipx(server: dict[str, Any]) -> dict[str, Any]:
    return next(module for module in server["modules"] if module["id"] == "ipx")


def _output(server: dict[str, Any], output_id: str) -> dict[str, Any]:
    return next(output for output in _ipx(server)["outputs"] if output["id"] == output_id)


@pytest.fixture
async def server(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> dict[str, Any]:
    """Set up the entry against a fake platform; change the returned dict to change what it answers."""
    state: dict[str, Any] = {"modules": copy.deepcopy(MODULES), "status": copy.deepcopy(STATUS)}

    async def user() -> dict[str, Any]:
        return {"id": "u", "modules": copy.deepcopy(state["modules"])}

    async def module(module_id: str) -> dict[str, Any]:
        return copy.deepcopy(next(m for m in state["modules"] if m["id"] == module_id))

    async def device(gateway_serial: str, endpoint: str, child_serial: str | None = None) -> dict:
        if child_serial is None:
            return {"wifiLink": True}
        return copy.deepcopy(state["status"]) if endpoint == "status" else DEVICE_PROGRAMS

    async def send(output_id: str, values: dict[str, Any]) -> dict[str, Any]:
        # The platform stores the request until the electrolyser picks it up.
        _output(state, output_id)["pendingIpxData"].update(values)
        return {}

    mock_client.async_get_user_with_modules.side_effect = user
    mock_client.async_get_module.side_effect = module
    mock_client.async_get_device.side_effect = device
    mock_client.async_send_ipx_data.side_effect = send
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    return state


def _entity_id(hass: HomeAssistant, platform: str, key: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(platform, "myindygo", f"{SERIAL}_{key}")
    assert entity_id, f"no {platform} entity for {key}"
    return entity_id


def _state(hass: HomeAssistant, platform: str, key: str):
    return hass.states.get(_entity_id(hass, platform, key))


async def _set_number(hass: HomeAssistant, key: str, value: float) -> None:
    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": _entity_id(hass, "number", key), "value": value},
        blocking=True,
    )


async def _select(hass: HomeAssistant, key: str, option: str) -> None:
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": _entity_id(hass, "select", key), "option": option},
        blocking=True,
    )


async def _press(hass: HomeAssistant, key: str) -> None:
    await hass.services.async_call(
        "button", "press", {"entity_id": _entity_id(hass, "button", key)}, blocking=True
    )


async def _cloud_refresh(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await entry.runtime_data.cloud.async_refresh()
    await hass.async_block_till_done()


def _report(server: dict[str, Any], output_id: str, **values: Any) -> None:
    """The electrolyser took the pending settings and reported new values."""
    output = _output(server, output_id)
    output["pendingIpxData"] = {}
    output["ipxData"].update(values)
    _ipx(server)["lastIpxCommunication"] = "2026-11-14T14:15:00.000Z"


def _warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.WARNING and record.name.startswith("custom_components.myindygo")
    ]


async def test_entities(hass: HomeAssistant, server: dict[str, Any]) -> None:
    ph = _state(hass, "number", "ph_setpoint_control")
    assert ph.state == "7.2"
    assert (ph.attributes["min"], ph.attributes["max"], ph.attributes["step"]) == (6.8, 7.6, 0.1)
    assert ph.attributes["mode"] == "box"
    assert ph.attributes["pending_value"] is None
    production = _state(hass, "number", "production_setpoint_control")
    assert production.state == "10"
    assert (production.attributes["min"], production.attributes["max"]) == (0, 100)
    assert production.attributes["step"] == 1
    assert production.attributes["unit_of_measurement"] == "%"

    ph_mode = _state(hass, "select", "ph_regulation_control")
    assert ph_mode.state == "on"
    assert ph_mode.attributes["options"] == ["off", "on"]
    electrolysis = _state(hass, "select", "electrolysis_mode_control")
    assert electrolysis.state == "percentage"
    assert electrolysis.attributes["options"] == ["off", "percentage"]

    for key in ("boost_12h", "boost_24h", "boost_stop"):
        assert _state(hass, "button", key)
    pending = _state(hass, "binary_sensor", "settings_pending")
    assert pending.state == "off"
    assert pending.attributes["pending"] == {}

    registry = er.async_get(hass)
    assert registry.async_get(_entity_id(hass, "number", "ph_setpoint_control")).entity_category == "config"


async def test_setpoint_pending_then_applied(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    server: dict[str, Any],
    mock_config_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await _set_number(hass, "ph_setpoint_control", 7.3)

    mock_client.async_send_ipx_data.assert_awaited_once_with("out-ph", {"pHSetpoint": 7.3})
    mock_client.async_get_module.assert_awaited_once_with("ipx")
    # The electrolyser has not taken it yet: the reported value is kept, the request is pending.
    ph = _state(hass, "number", "ph_setpoint_control")
    assert ph.state == "7.2"
    assert ph.attributes["pending_value"] == 7.3
    pending = _state(hass, "binary_sensor", "settings_pending")
    assert pending.state == "on"
    assert pending.attributes["pending"] == {"pHSetpoint": 7.3}

    # Next cloud read: still pending.
    await _cloud_refresh(hass, mock_config_entry)
    assert _state(hass, "number", "ph_setpoint_control").state == "7.2"

    _report(server, "out-ph", pHSetpoint=7.3)
    with caplog.at_level(logging.DEBUG):
        await _cloud_refresh(hass, mock_config_entry)
    ph = _state(hass, "number", "ph_setpoint_control")
    assert ph.state == "7.3"
    assert ph.attributes["pending_value"] is None
    assert _state(hass, "binary_sensor", "settings_pending").state == "off"
    assert "pHSetpoint=7.3 applied" in caplog.text
    assert not _warnings(caplog)


async def test_setting_not_applied_is_logged(
    hass: HomeAssistant,
    server: dict[str, Any],
    mock_config_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await _set_number(hass, "production_setpoint_control", 40)
    _report(server, "out-elec")  # pending emptied, value unchanged
    with caplog.at_level(logging.WARNING):
        await _cloud_refresh(hass, mock_config_entry)
    assert _warnings(caplog) == ["percentageSetpoint=40 was not applied by IPX-CCCCCC: it reports 10"]
    assert _state(hass, "number", "production_setpoint_control").state == "10"


async def test_request_still_pending_is_logged_once(
    hass: HomeAssistant,
    server: dict[str, Any],
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await _select(hass, "electrolysis_mode_control", "off")
    assert _state(hass, "select", "electrolysis_mode_control").state == "percentage"
    assert _state(hass, "select", "electrolysis_mode_control").attributes["pending_value"] == "off"

    freezer.tick(ipx_settings.PENDING_WARNING_DELAY + timedelta(minutes=1))
    with caplog.at_level(logging.WARNING):
        await _cloud_refresh(hass, mock_config_entry)
        await _cloud_refresh(hass, mock_config_entry)
    warnings = _warnings(caplog)
    assert len(warnings) == 1
    assert warnings[0].startswith("electrolyzerMode=0 for IPX-CCCCCC is still waiting")


async def test_select_and_unchanged_value(
    hass: HomeAssistant, mock_client: AsyncMock, server: dict[str, Any]
) -> None:
    await _select(hass, "ph_regulation_control", "on")  # already on
    await _set_number(hass, "production_setpoint_control", 10)  # already 10
    mock_client.async_send_ipx_data.assert_not_awaited()

    await _select(hass, "ph_regulation_control", "off")
    mock_client.async_send_ipx_data.assert_awaited_once_with("out-ph", {"pHMode": 0})
    assert _state(hass, "select", "ph_regulation_control").state == "on"


async def test_boost_buttons(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    server: dict[str, Any],
    mock_config_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await _press(hass, "boost_24h")
    mock_client.async_send_ipx_data.assert_awaited_once_with("out-elec", {"boostCommand": 24})
    assert _state(hass, "binary_sensor", "boost").state == "off"
    assert _state(hass, "binary_sensor", "settings_pending").attributes["pending"] == {"boostCommand": 24}

    _report(server, "out-elec", boostEnabled=True, boostRemainingTime=1440)
    with caplog.at_level(logging.DEBUG):
        await _cloud_refresh(hass, mock_config_entry)
    assert _state(hass, "binary_sensor", "boost").state == "on"
    assert "boostCommand=24 applied" in caplog.text

    await _press(hass, "boost_stop")
    assert mock_client.async_send_ipx_data.await_args.args == ("out-elec", {"boostCommand": 0})


async def test_superseded_request_is_not_reported(
    hass: HomeAssistant,
    server: dict[str, Any],
    mock_config_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await _press(hass, "boost_12h")
    await _press(hass, "boost_stop")
    assert _state(hass, "binary_sensor", "settings_pending").attributes["pending"] == {"boostCommand": 0}

    _report(server, "out-elec", boostEnabled=False)
    with caplog.at_level(logging.WARNING):
        await _cloud_refresh(hass, mock_config_entry)
    assert not _warnings(caplog)


@pytest.mark.parametrize(
    ("platform_call", "error"),
    [
        (("ph_setpoint_control", 7.25), "invalid_setting"),
        (("production_setpoint_control", 12.5), "invalid_setting"),
    ],
)
async def test_value_off_step_is_refused(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    server: dict[str, Any],
    platform_call: tuple[str, float],
    error: str,
) -> None:
    with pytest.raises(ServiceValidationError) as err:
        await _set_number(hass, *platform_call)
    assert err.value.translation_key == error
    mock_client.async_send_ipx_data.assert_not_awaited()


@pytest.mark.parametrize(
    ("key", "value"),
    [("ph_setpoint_control", 7.7), ("ph_setpoint_control", 6.7), ("production_setpoint_control", 101)],
)
async def test_out_of_range_is_refused(
    hass: HomeAssistant, mock_client: AsyncMock, server: dict[str, Any], key: str, value: float
) -> None:
    with pytest.raises(ServiceValidationError):
        await _set_number(hass, key, value)
    mock_client.async_send_ipx_data.assert_not_awaited()


def test_validate_out_of_range() -> None:
    module = copy.deepcopy(next(m for m in MODULES if m["id"] == "ipx"))
    for key, value in (("pHSetpoint", 7.7), ("percentageSetpoint", -1), ("boostCommand", 6)):
        with pytest.raises(ServiceValidationError):
            ipx_settings.validate(module, 1, key, value)
    assert ipx_settings.validate(module, 1, "pHSetpoint", 7.30000001) == 7.3


async def test_coarse_production_step(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    modules = copy.deepcopy(MODULES)
    next(m for m in modules if m["id"] == "ipx")["ipxData"]["configurationCode"] = "03000000"
    mock_client.async_get_user_with_modules.return_value = {"id": "u", "modules": modules}
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert _state(hass, "number", "production_setpoint_control").attributes["step"] == 5
    with pytest.raises(ServiceValidationError) as err:
        await _set_number(hass, "production_setpoint_control", 12)
    assert err.value.translation_key == "invalid_setting"
    mock_client.async_send_ipx_data.assert_not_awaited()


async def test_setpoint_needs_its_mode(
    hass: HomeAssistant, mock_client: AsyncMock, server: dict[str, Any], mock_config_entry: MockConfigEntry
) -> None:
    _output(server, "out-ph")["ipxData"]["pHMode"] = 0
    _output(server, "out-elec")["ipxData"]["electrolyzerMode"] = 0
    await _cloud_refresh(hass, mock_config_entry)
    with pytest.raises(ServiceValidationError) as err:
        await _set_number(hass, "ph_setpoint_control", 7.3)
    assert err.value.translation_key == "ph_regulation_off"
    with pytest.raises(ServiceValidationError) as err:
        await _set_number(hass, "production_setpoint_control", 30)
    assert err.value.translation_key == "production_not_percentage"
    mock_client.async_send_ipx_data.assert_not_awaited()

    # A pending mode change counts, like in the app.
    await _select(hass, "ph_regulation_control", "on")
    await _set_number(hass, "ph_setpoint_control", 7.3)
    assert mock_client.async_send_ipx_data.await_count == 2


async def test_filtration_must_run(
    hass: HomeAssistant, mock_client: AsyncMock, server: dict[str, Any], mock_config_entry: MockConfigEntry
) -> None:
    server["status"]["pool"][0]["value"] = 0
    await mock_config_entry.runtime_data.live.async_refresh()
    with pytest.raises(ServiceValidationError) as err:
        await _set_number(hass, "ph_setpoint_control", 7.3)
    assert err.value.translation_key == "filtration_stopped"

    # Pool controller status unknown: refused too.
    mock_config_entry.runtime_data.live.async_set_updated_data({})
    with pytest.raises(ServiceValidationError) as err:
        await _press(hass, "boost_12h")
    assert err.value.translation_key == "filtration_unknown"
    mock_client.async_send_ipx_data.assert_not_awaited()


async def test_no_boost_while_wintering(
    hass: HomeAssistant, mock_client: AsyncMock, server: dict[str, Any], mock_config_entry: MockConfigEntry
) -> None:
    _output(server, "out-elec")["ipxData"]["isWintered"] = True
    await _cloud_refresh(hass, mock_config_entry)
    with pytest.raises(ServiceValidationError) as err:
        await _press(hass, "boost_12h")
    assert err.value.translation_key == "boost_wintering"
    mock_client.async_send_ipx_data.assert_not_awaited()


async def test_api_error(hass: HomeAssistant, mock_client: AsyncMock, server: dict[str, Any]) -> None:
    mock_client.async_send_ipx_data.side_effect = MyIndygoConnectionError(
        "/api/outputs/out-ph/ipxData: HTTP 500"
    )
    with pytest.raises(HomeAssistantError) as err:
        await _set_number(hass, "ph_setpoint_control", 7.3)
    assert err.value.translation_key == "setting_failed"
    assert "HTTP 500" in err.value.translation_placeholders["error"]
    # Nothing is shown as pending.
    assert _state(hass, "number", "ph_setpoint_control").attributes["pending_value"] is None
    assert _state(hass, "binary_sensor", "settings_pending").state == "off"


async def test_auth_error_starts_reauth(
    hass: HomeAssistant, mock_client: AsyncMock, server: dict[str, Any], mock_config_entry: MockConfigEntry
) -> None:
    mock_client.async_send_ipx_data.side_effect = MyIndygoAuthError("denied")
    with pytest.raises(HomeAssistantError) as err:
        await _press(hass, "boost_12h")
    assert err.value.translation_key == "auth_failed"
    await hass.async_block_till_done()
    assert any(mock_config_entry.async_get_active_flows(hass, {"reauth"}))


async def test_reread_failure_keeps_the_local_request(
    hass: HomeAssistant, mock_client: AsyncMock, server: dict[str, Any]
) -> None:
    mock_client.async_get_module.side_effect = MyIndygoConnectionError("down")
    await _set_number(hass, "production_setpoint_control", 40)
    assert _state(hass, "number", "production_setpoint_control").attributes["pending_value"] == 40
    assert _state(hass, "binary_sensor", "settings_pending").state == "on"


# API client -------------------------------------------------------------------------------

IPX_PATH = "/api/outputs/out-ph/ipxData"


async def test_send_ipx_data_body() -> None:
    session = FakeSession()
    session.add("POST", "/oauth2/token", payload=TOKEN)
    session.add("POST", IPX_PATH, payload={"ok": True})
    assert await make_client(session).async_send_ipx_data("out-ph", {"pHSetpoint": 7.3}) == {"ok": True}
    call = session.calls[1]
    assert call["json"] == {"ipxData": {"pHSetpoint": 7.3}}
    assert call["headers"]["Authorization"] == "Bearer abc"


async def test_send_ipx_data_relogin_once_on_401() -> None:
    session = FakeSession()
    session.add("POST", "/oauth2/token", payload=TOKEN)
    session.add("POST", IPX_PATH, status=401, payload=None)
    session.add("POST", "/oauth2/token", payload={**TOKEN, "access_token": "new"})
    session.add("POST", IPX_PATH, payload=True)
    assert await make_client(session).async_send_ipx_data("out-ph", {"pHMode": 1}) == {}
    assert session.calls[-1]["headers"]["Authorization"] == "Bearer new"
    assert session.calls[-1]["json"] == {"ipxData": {"pHMode": 1}}


@pytest.mark.parametrize(
    "answer", [(500, None), (200, {"err": "invalid value"}), (200, {"error": {"code": "x"}})]
)
async def test_send_ipx_data_errors(answer: tuple[int, Any]) -> None:
    session = FakeSession()
    session.add("POST", "/oauth2/token", payload=TOKEN)
    session.add("POST", IPX_PATH, status=answer[0], payload=answer[1])
    with pytest.raises(MyIndygoConnectionError):
        await make_client(session).async_send_ipx_data("out-ph", {"pHSetpoint": 7.3})


async def test_send_ipx_data_denied_twice() -> None:
    session = FakeSession()
    session.add("POST", "/oauth2/token", payload=TOKEN)
    session.add("POST", IPX_PATH, status=403, payload=None)
    session.add("POST", "/oauth2/token", payload=TOKEN)
    session.add("POST", IPX_PATH, status=403, payload=None)
    with pytest.raises(MyIndygoAuthError):
        await make_client(session).async_send_ipx_data("out-ph", {"pHSetpoint": 7.3})
