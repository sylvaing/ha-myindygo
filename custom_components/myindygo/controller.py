"""Shared description of the pool controller (LR-PC) entities.

Each entity reads the live status (refreshed every few minutes through the gateway) and, when
needed, the compiled programs from the cloud coordinator.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .coordinator import is_pool_controller
from .entity import MyIndygoEntity

if TYPE_CHECKING:
    from . import MyIndygoData


@dataclass(frozen=True)
class ControllerContext:
    """What a controller entity needs to compute its value."""

    status: dict[str, Any] | None
    device_programs: dict[str, Any] | None
    module: dict[str, Any]


def controllers(data: MyIndygoData) -> list[dict[str, Any]]:
    """Return the pool controller modules of the account."""
    return [module for module in data.cloud.data.modules.values() if is_pool_controller(module)]


def output_indexes(module: dict[str, Any]) -> list[int]:
    """Indexes of the outputs of a controller (0 = filtration)."""
    return sorted(int(output["index"]) for output in module.get("outputs", []) if "index" in output)


def output_naming(index: int, filtration_key: str, output_key: str) -> tuple[str, dict[str, str] | None]:
    """Translation key and placeholders: output 0 is the filtration pump on an LR-PC."""
    if index == 0:
        return filtration_key, None
    return output_key, {"number": str(index)}


class ControllerEntity(MyIndygoEntity):
    """Entity of a pool controller, refreshed by the live coordinator."""

    def __init__(
        self,
        data: MyIndygoData,
        module: dict[str, Any],
        key: str,
        translation_key: str,
        placeholders: dict[str, str] | None = None,
    ) -> None:
        super().__init__(data.live, module, key, translation_key, placeholders)
        self._data = data

    @property
    def context(self) -> ControllerContext:
        live = self._data.live.data or {}
        cloud = self._data.cloud.data
        return ControllerContext(
            status=live.get(self.module_id),
            device_programs=cloud.device_programs.get(self.module_id) if cloud else None,
            module=cloud.modules.get(self.module_id, {}) if cloud else {},
        )

    async def async_added_to_hass(self) -> None:
        """Also follow the cloud coordinator (programs), which keeps it polling."""
        await super().async_added_to_hass()
        self.async_on_remove(self._data.cloud.async_add_listener(self._handle_coordinator_update))

    @property
    def available(self) -> bool:
        return super().available and self.context.status is not None


ValueFn = Callable[[ControllerContext], Any]
