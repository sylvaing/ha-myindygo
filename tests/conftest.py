"""Shared fixtures for the MyIndygo tests."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.myindygo.const import DOMAIN

# Anonymised module list: a gateway, a pool controller behind it and an IPX behind the controller.
MODULES = [
    {
        "id": "gw",
        "name": "LRMB10-AAAAAA",
        "manufacturerType": "10",
        "type": "lr-mb-10",
        "serialNumber": "10000000AAAAAA0001",
        "softwareVersion": "6.3.1",
    },
    {
        "id": "ipx",
        "name": "IPX-CCCCCC",
        "manufacturerType": "FD",
        "type": "ipx",
        "serialNumber": "FD0001020200112233CCCCCC0001",
        "ipxRelay": "pc",
        "typeIpx": 1,
        "softwareVersion": "3.3",
        "lastIpxCommunication": "2026-11-14T14:01:07.000Z",
        "ipxData": {
            "cellVoltage": 23,
            "totalElectrolyseDuration": 2331,
            "deviceState": {
                "shutterEntry": False,
                "cmdEntry": False,
                "flowEntry": True,
                "canPhEntry": False,
                "boostEnabled": False,
                "pHInjection": True,
                "prodStatus": True,
            },
        },
        "inputs": [
            {
                "index": 1,
                "type": 6,
                "unit": 4,
                "lastValue": {"value": 7.2, "date": "2026-11-14T14:01:07.000Z"},
            },
            {"index": 2, "type": 0, "unit": 0, "lastValue": None},
        ],
        "outputs": [
            {
                "index": 0,
                "id": "out-ph",
                "ipxData": {
                    "type": 1,
                    "pHSetpoint": 7.2,
                    "pHMode": 1,
                    "stateAlarms": [],
                    "isWintered": False,
                },
                "pendingIpxData": {},
            },
            {
                "index": 1,
                "id": "out-elec",
                "ipxData": {
                    "type": 4,
                    "saltValue": 3.7,
                    "percentageSetpoint": 10,
                    "electrolyzerMode": 1,
                    "boostRemainingTime": 0,
                    "boostEnabled": False,
                    "stateAlarms": ["Low salt"],
                    "isWintered": False,
                },
                "pendingIpxData": {},
            },
        ],
    },
    {
        "id": "pc",
        "name": "LRPC-BBBBBB",
        "manufacturerType": "15",
        "type": "lr-pc",
        "serialNumber": "150302BBBBBB0001",
        "relay": "gw",
        "softwareVersion": "7.0.9",
        "inputs": [
            {"index": 1, "type": 5, "unit": 2, "expression": "x/100.0"},
            {"index": 2, "type": 0, "unit": 0, "expression": "x"},
        ],
        "outputs": [{"index": 0}, {"index": 1}, {"index": 2}],
    },
]


POOL_STATUS = {
    "id": "pool1",
    "status": {"lastTemperatureMeasure": {"value": 19.29, "date": 1794665160}},
}
STATUS = {
    "dialogTimeStamp": "2026-11-14T14:14:47Z",
    "temperature": 29,
    "pool": [
        {"index": 0, "value": 1, "time": "00:46", "tempRef": 4, "info": ["pgm"]},
        {"index": 1, "value": 1, "time": "01:30", "tempRef": 4, "origin": 2},
        {"index": 2, "value": 0, "time": "00:00", "tempRef": 4},
    ],
    "sensorState": [{"index": 0, "value": 1929}, {"index": 1, "value": 2147483647}],
    "inputsAlerts": [],
    "radio": [],
}
# Thermo-adaptive filtration schedule as compiled in a real controller (same mask every day).
FILTRATION_SCHED = [
    [4194336, 4194336, 28672, 61440, 63488, 129024, 261120, 1047552, 2096640, 8388352, 16777152, 16777212],
    [4194336, 4194336, 28672, 61440, 63488, 129024, 261120, 1047552, 2096640, 8388352, 16777152, 16777212],
    [4194336, 4194336, 28672, 61440, 63488, 129024, 261120, 1047552, 2096640, 8388352, 16777152, 16777212],
    [4194336, 4194336, 28672, 61440, 63488, 129024, 261120, 1047552, 2096640, 8388352, 16777152, 16777212],
    [4194336, 4194336, 28672, 61440, 63488, 129024, 261120, 1047552, 2096640, 8388352, 16777152, 16777212],
    [4194336, 4194336, 28672, 61440, 63488, 129024, 261120, 1047552, 2096640, 8388352, 16777152, 16777212],
    [4194336, 4194336, 28672, 61440, 63488, 129024, 261120, 1047552, 2096640, 8388352, 16777152, 16777212],
]
THRESHOLDS = [10, 12, 14, 16, 18, 20, 22, 24, 26, 28, 30, 127]
DEVICE_PROGRAMS = {
    "programs": [
        {
            "index": 0,
            "programCharacteristics": {"programType": 4, "mode": 2, "rule": 1, "ths": THRESHOLDS},
            "sched": FILTRATION_SCHED,
        },
        {
            "index": 1,
            "programCharacteristics": {"programType": 8, "mode": 2, "rule": 0, "ths": THRESHOLDS},
            "sched": [[0] * 12] * 7,
        },
        {
            "index": 2,
            "programCharacteristics": {"programType": 8, "mode": 0, "rule": 0, "ths": THRESHOLDS},
            "sched": [[0] * 12] * 7,
        },
    ]
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Allow Home Assistant to load the custom integration in every test."""
    return


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """A configured MyIndygo account."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="user@example.com",
        unique_id="user@example.com",
        data={CONF_EMAIL: "user@example.com", CONF_PASSWORD: "secret"},
    )


@pytest.fixture
def mock_client() -> Generator[AsyncMock]:
    """Patch the API client everywhere it is created."""
    with (
        patch("custom_components.myindygo.config_flow.MyIndygoApiClient", autospec=True) as flow_cls,
        patch("custom_components.myindygo.MyIndygoApiClient", new=flow_cls),
    ):
        client = flow_cls.return_value
        client.async_get_user_with_modules.return_value = {"id": "u", "modules": MODULES}
        client.async_get_pools.return_value = [{"id": "pool1"}]
        client.async_get_pool_status.return_value = POOL_STATUS
        client.async_get_programs.return_value = {"programs": [{"index": 0}]}
        client.async_get_device.side_effect = _device
        yield client


async def _device(gateway_serial: str, endpoint: str, child_serial: str | None = None) -> dict:
    assert gateway_serial == "10000000AAAAAA0001"
    assert child_serial == "150302BBBBBB0001"
    return {"status": STATUS, "programs": DEVICE_PROGRAMS}[endpoint]
