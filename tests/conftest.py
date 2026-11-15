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
        yield client
