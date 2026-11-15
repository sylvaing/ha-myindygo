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
    },
    {
        "id": "pc",
        "name": "LRPC-BBBBBB",
        "manufacturerType": "15",
        "type": "lr-pc",
        "serialNumber": "150302BBBBBB0001",
        "relay": "gw",
        "softwareVersion": "7.0.9",
    },
]


POOL_STATUS = {
    "id": "pool1",
    "status": {"lastTemperatureMeasure": {"value": 19.29, "date": 1794665160}},
}
STATUS = {
    "dialogTimeStamp": "2026-11-14T14:14:47Z",
    "pool": [{"index": 0, "value": 1, "time": "00:46", "tempRef": 4, "info": ["pgm"]}],
    "sensorState": [{"index": 0, "value": 1929}],
    "radio": [],
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
    return {"status": STATUS, "programs": {"programs": [{"index": 0, "sched": []}]}}[endpoint]
