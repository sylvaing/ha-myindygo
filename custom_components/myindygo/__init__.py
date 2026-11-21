"""The MyIndygo (Solem) integration (unofficial).

Set-up logs in to the MyIndygo cloud, starts the two data coordinators and registers one Home
Assistant device per module of the account (gateway, pool controller, IPX). The outputs of a pool
controller accept manual commands (forced run, boost, pause, stop) as entity actions.
"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import MyIndygoApiClient
from .commands import async_setup_services
from .const import CONF_CLIENT_ID, DOMAIN, MANUFACTURER, MODEL_NAMES
from .coordinator import MyIndygoCloudCoordinator, MyIndygoLiveCoordinator

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SELECT, Platform.SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


@dataclass
class MyIndygoData:
    """Runtime data of a config entry."""

    client: MyIndygoApiClient
    cloud: MyIndygoCloudCoordinator
    live: MyIndygoLiveCoordinator


type MyIndygoConfigEntry = ConfigEntry[MyIndygoData]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the entity actions (manual commands of the controller outputs)."""
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: MyIndygoConfigEntry) -> bool:
    """Set up MyIndygo from a config entry."""
    client = MyIndygoApiClient(
        async_get_clientsession(hass),
        entry.data[CONF_EMAIL],
        entry.data[CONF_PASSWORD],
        client_id=entry.options.get(CONF_CLIENT_ID) or None,
    )
    # The cloud data is required: auth errors start a reauth flow, connection errors a retry.
    cloud = MyIndygoCloudCoordinator(hass, entry, client)
    await cloud.async_config_entry_first_refresh()
    # The live status is not: a gateway outage must not block the set-up.
    live = MyIndygoLiveCoordinator(hass, entry, client, cloud)
    await live.async_refresh()

    _async_register_devices(hass, entry, list(cloud.data.modules.values()))
    entry.runtime_data = MyIndygoData(client=client, cloud=cloud, live=live)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: MyIndygoConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


def _async_register_devices(hass: HomeAssistant, entry: ConfigEntry, modules: list[dict]) -> None:
    """Create one device per module, linked to its parent (gateway -> controller -> IPX)."""
    registry = dr.async_get(hass)
    by_id = {module["id"]: module for module in modules}

    def depth(module: dict) -> int:
        parent = by_id.get(module.get("relay") or module.get("ipxRelay"))
        return 1 + depth(parent) if parent else 0

    # Parents first, so that via_device_id always points to an existing device. These are
    # separate physical devices (not child devices of one another), linked by radio.
    device_ids: dict[str, str] = {}
    for module in sorted(modules, key=depth):
        parent = by_id.get(module.get("relay") or module.get("ipxRelay"))
        model_code = str(module.get("manufacturerType", "")).upper()
        device = registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, module["serialNumber"])},
            manufacturer=MANUFACTURER,
            model=MODEL_NAMES.get(model_code, module.get("type")),
            name=module.get("name") or module["serialNumber"],
            serial_number=module["serialNumber"],
            sw_version=module.get("softwareVersion"),
            hw_version=module.get("hardwareVersion"),
            via_device_id=device_ids.get(parent["id"]) if parent else None,
        )
        device_ids[module["id"]] = device.id
