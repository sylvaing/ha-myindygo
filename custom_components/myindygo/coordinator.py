"""Data update coordinators for MyIndygo.

Two coordinators keep the load on the vendor servers low:

* ``MyIndygoLiveCoordinator`` (default every 2 min) reads the real-time ``status`` of each pool
  controller through the device relay (cloud -> gateway -> controller cache);
* ``MyIndygoCloudCoordinator`` (default every 15 min) reads what only changes slowly: modules
  (including the IPX electrolyser data, refreshed by the hardware every ~10-15 min), pools and
  their latest measures, and the programs of the pool controllers.

A gateway outage only fails the live coordinator: the cloud data stays available.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import MyIndygoApiClient, MyIndygoAuthError, MyIndygoConnectionError
from .const import (
    CONF_LIVE_INTERVAL,
    CONF_PLATFORM_INTERVAL,
    DEFAULT_LIVE_INTERVAL,
    DEFAULT_PLATFORM_INTERVAL,
    DOMAIN,
    MANUFACTURER_TYPE_GATEWAY_LR_MB_10,
    MANUFACTURER_TYPE_POOL_CONTROLLER_LR_PC,
)

if TYPE_CHECKING:
    from . import MyIndygoConfigEntry

_LOGGER = logging.getLogger(__name__)


def is_pool_controller(module: dict[str, Any]) -> bool:
    """Return True for a pool controller reachable through a gateway (LR-PC)."""
    return str(module.get("manufacturerType", "")).upper() == MANUFACTURER_TYPE_POOL_CONTROLLER_LR_PC


@dataclass
class CloudData:
    """Slow-changing data read from the MyIndygo platform."""

    # module id -> module (with inputs, outputs, status and, for an IPX, ipxData)
    modules: dict[str, dict[str, Any]] = field(default_factory=dict)
    # pool id -> pool with its latest measures (``status``)
    pools: dict[str, dict[str, Any]] = field(default_factory=dict)
    # controller module id -> programs as stored by the platform (rules, schedules, offset)
    programs: dict[str, dict[str, Any]] = field(default_factory=dict)
    # controller module id -> programs as compiled in the controller (``sched`` matrix)
    device_programs: dict[str, dict[str, Any]] = field(default_factory=dict)
    # gateway module id -> ``information`` read through the relay (uptime, links, firmware)
    gateway_info: dict[str, dict[str, Any]] = field(default_factory=dict)


def is_gateway(module: dict[str, Any]) -> bool:
    """Return True for a MyIndygo gateway (LR-MB-10)."""
    return str(module.get("manufacturerType", "")).upper() == MANUFACTURER_TYPE_GATEWAY_LR_MB_10


def gateway_of(module: dict[str, Any], modules: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    """Return the gateway relaying a radio module, if any."""
    return modules.get(module.get("relay") or "")


class MyIndygoCloudCoordinator(DataUpdateCoordinator[CloudData]):
    """Read modules, pools and programs from the MyIndygo platform."""

    config_entry: MyIndygoConfigEntry

    def __init__(self, hass: HomeAssistant, entry: MyIndygoConfigEntry, client: MyIndygoApiClient) -> None:
        minutes = entry.options.get(CONF_PLATFORM_INTERVAL, DEFAULT_PLATFORM_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} cloud",
            update_interval=timedelta(minutes=minutes),
        )
        self.client = client

    async def _async_update_data(self) -> CloudData:
        try:
            user = await self.client.async_get_user_with_modules()
            modules = {module["id"]: module for module in user.get("modules", [])}
            data = CloudData(modules=modules)

            for pool in await self.client.async_get_pools():
                data.pools[pool["id"]] = await self.client.async_get_pool_status(pool["id"])

            for module in modules.values():
                if is_gateway(module):
                    try:
                        data.gateway_info[module["id"]] = await self.client.async_get_device(
                            module["serialNumber"], "information"
                        )
                    except MyIndygoConnectionError as err:
                        _LOGGER.debug("Cannot read the information of %s: %s", module.get("name"), err)
                if not is_pool_controller(module):
                    continue
                data.programs[module["id"]] = await self.client.async_get_programs(module["id"])
                gateway = gateway_of(module, modules)
                if gateway is None:
                    continue
                try:
                    data.device_programs[module["id"]] = await self.client.async_get_device(
                        gateway["serialNumber"], "programs", module["serialNumber"]
                    )
                except MyIndygoConnectionError as err:
                    # Gateway offline: keep the platform data, entities using the compiled
                    # programs will be unavailable until the next refresh.
                    _LOGGER.debug("Cannot read the programs of %s: %s", module.get("name"), err)
        except MyIndygoAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except MyIndygoConnectionError as err:
            raise UpdateFailed(f"MyIndygo cloud unavailable: {err}") from err
        return data


# Consecutive relay failures tolerated before a controller's live entities become unavailable.
# The gateway's cloud connection drops for a few minutes several times a day; with the default
# 2-minute interval, 3 failures keep the last status for up to ~6 minutes.
RELAY_GRACE_FAILURES = 3


class MyIndygoLiveCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """Read the real-time status of each pool controller through its gateway.

    Data: controller module id -> device ``status`` (outputs, raw sensor values, radio state).

    A short relay outage keeps the last status of a controller for a few polls
    (``RELAY_GRACE_FAILURES``) instead of making all its entities unavailable at once; the
    ``Last communication`` entity still shows how old the status is.
    """

    config_entry: MyIndygoConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: MyIndygoConfigEntry,
        client: MyIndygoApiClient,
        cloud: MyIndygoCloudCoordinator,
    ) -> None:
        minutes = entry.options.get(CONF_LIVE_INTERVAL, DEFAULT_LIVE_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} live",
            update_interval=timedelta(minutes=minutes),
        )
        self.client = client
        self.cloud = cloud
        self._failures: dict[str, int] = {}

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        modules = self.cloud.data.modules if self.cloud.data else {}
        targets = [
            (module, gateway)
            for module in modules.values()
            if is_pool_controller(module) and (gateway := gateway_of(module, modules)) is not None
        ]
        previous = self.data or {}
        result: dict[str, dict[str, Any]] = {}
        errors: list[str] = []
        for module, gateway in targets:
            module_id = module["id"]
            try:
                result[module_id] = await self.client.async_get_device(
                    gateway["serialNumber"], "status", module["serialNumber"]
                )
            except MyIndygoAuthError as err:
                raise ConfigEntryAuthFailed(str(err)) from err
            except MyIndygoConnectionError as err:
                failures = self._failures.get(module_id, 0) + 1
                self._failures[module_id] = failures
                errors.append(f"{module.get('name')}: {err}")
                if module_id in previous and failures < RELAY_GRACE_FAILURES:
                    _LOGGER.debug(
                        "Keeping the last status of %s (relay failure %s/%s): %s",
                        module.get("name"),
                        failures,
                        RELAY_GRACE_FAILURES,
                        err,
                    )
                    result[module_id] = previous[module_id]
            else:
                self._failures.pop(module_id, None)
        if targets and not result:
            raise UpdateFailed(f"No pool controller status could be read ({'; '.join(errors)})")
        return result
