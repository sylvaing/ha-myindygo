"""Tests for the MyIndygo diagnostics."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.myindygo.diagnostics import async_get_config_entry_diagnostics

from .conftest import MODULES


async def test_diagnostics_are_redacted(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    mock_client.async_get_pool_status.return_value = {
        "id": "pool1",
        "address": "1 rue de la Piscine",
        "latitude": 43.6,
        "country": "France",
        "daylyWeatherForecast": {"Headline": {"Link": "https://weather.example/my-town"}},
        "status": {"lastTemperatureMeasure": {"value": 19.29}},
    }
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)

    result = await async_get_config_entry_diagnostics(hass, mock_config_entry)
    text = json.dumps(result)

    assert result["entry"]["data"] == {"email": "**REDACTED**", "password": "**REDACTED**"}
    for secret in ("user@example.com", "secret", "1 rue de la Piscine", "43.6", "France", "my-town"):
        assert secret not in text
    for module in MODULES:
        assert module["serialNumber"] not in text
        assert module["name"] not in text

    # The data needed to debug is still there.
    assert result["cloud"]["last_update_success"] is True
    assert result["cloud"]["data"]["pools"]["pool1"]["status"]["lastTemperatureMeasure"]["value"] == 19.29
    assert result["live"]["data"]["pc"]["sensorState"][0]["value"] == 1929
    assert set(result["cloud"]["data"]["modules"]) == {"gw", "pc", "ipx"}
