"""Diagnostics for MyIndygo: raw API data with personal information redacted."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant

from . import MyIndygoConfigEntry
from .const import CONF_CLIENT_ID

# Keys removed wherever they appear in the API payloads: identity, contact details, location,
# serial numbers and network addresses, tokens and free-text names (module names embed part of
# the serial number). Weather forecasts are dropped too: they are bulky and location-based.
TO_REDACT = {
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_CLIENT_ID,
    "firstName",
    "lastName",
    "birthday",
    "address",
    "addressLine1",
    "addressWeather",
    "city",
    "cityName",
    "country",
    "countryName",
    "departementName",
    "postalCode",
    "locationKey",
    "latitude",
    "longitude",
    "mobilePhone",
    "otherPhone",
    "phoneNumberLock",
    "agency",
    "owner",
    "users",
    "adminUsers",
    "userGroups",
    "getUserNameWithEmail",
    "gcmTokens",
    "apnsTokens",
    "token",
    "securityKey",
    "serialNumber",
    "msn",
    "uuid",
    "mac",
    "macAddress",
    "BleMacAddress",
    "WifiMacAddress",
    "bluetoothMacAddress",
    "wifiMacAddress",
    "ethernetMacAddress",
    "ssid",
    "simcard",
    "simcards",
    "photo",
    "customPhoto",
    "name",
    "Name",
    "defaultName",
    "getName",
    "getEquipmentName",
    "xRef",
    "snapshotBy",
    "parent",
    "dailyWeatherForecast",
    "daylyWeatherForecast",  # sic, as spelled by the API
    "weeklyWeatherForecast",
    "hourlyWeatherForecast",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: MyIndygoConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    data = entry.runtime_data
    cloud = data.cloud
    live = data.live
    return async_redact_data(
        {
            "entry": {"data": dict(entry.data), "options": dict(entry.options)},
            "cloud": {
                "last_update_success": cloud.last_update_success,
                "update_interval": str(cloud.update_interval),
                "data": asdict(cloud.data) if cloud.data else None,
            },
            "live": {
                "last_update_success": live.last_update_success,
                "update_interval": str(live.update_interval),
                "data": live.data,
            },
        },
        TO_REDACT,
    )
