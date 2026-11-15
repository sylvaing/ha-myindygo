"""Gateway (LR-MB-10) helpers and base entity."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.util import dt as dt_util

from .coordinator import is_gateway
from .entity import MyIndygoEntity

if TYPE_CHECKING:
    from . import MyIndygoData


def gateways(data: MyIndygoData) -> list[dict[str, Any]]:
    """Return the gateway modules of the account."""
    return [module for module in data.cloud.data.modules.values() if is_gateway(module)]


def last_restart(info: dict[str, Any] | None) -> datetime | None:
    """Time of the last restart: gateway clock (``cdate``) minus uptime (``up``, seconds).

    Rounded to the minute so that the state does not change at every refresh.
    """
    if not info:
        return None
    now = dt_util.parse_datetime(str(info.get("cdate") or ""))
    uptime = info.get("up")
    if now is None or not isinstance(uptime, int):
        return None
    return (now - timedelta(seconds=uptime)).replace(second=0, microsecond=0)


GatewayFn = Callable[[dict[str, Any], dict[str, Any] | None], Any]


class GatewayEntity(MyIndygoEntity):
    """Entity of a gateway, refreshed by the cloud coordinator."""

    def __init__(
        self,
        data: MyIndygoData,
        module: dict[str, Any],
        key: str,
        value_fn: GatewayFn,
        *,
        needs_info: bool = False,
    ) -> None:
        super().__init__(data.cloud, module, key, key)
        self._data = data
        self._value_fn = value_fn
        self._needs_info = needs_info

    def _current(self) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        cloud = self._data.cloud.data
        if not cloud:
            return None, None
        return cloud.modules.get(self.module_id), cloud.gateway_info.get(self.module_id)

    @property
    def available(self) -> bool:
        module, info = self._current()
        return super().available and module is not None and (info is not None or not self._needs_info)

    def _value(self) -> Any:
        module, info = self._current()
        return self._value_fn(module, info) if module is not None else None
