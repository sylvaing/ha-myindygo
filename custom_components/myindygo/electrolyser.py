"""IPX PoolTech electrolyser (salt chlorinator + pH regulation) helpers and base entity.

All values come from the platform (``getUserWithHisModules``), which receives them from the
electrolyser through the pool controller and the gateway about every 10-15 minutes.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from .const import MANUFACTURER_TYPE_IPX
from .entity import MyIndygoEntity

if TYPE_CHECKING:
    from . import MyIndygoData

IPX_TYPE_POOLTECH = 1

# ipxData.type of the electrolyser's outputs
OUTPUT_PH_REGULATOR = 1
OUTPUT_ELECTROLYZER = 4

# Cloud input types
INPUT_PH = 6
INPUT_REDOX = 7

PH_MODES = {0: "off", 1: "on"}
ELECTROLYZER_MODES = {0: "off", 1: "percentage", 2: "auto"}

# ipxData.deviceState flags: key -> entity key. The polarity of the hardware inputs (flow,
# cover, pH can, external command) is not documented: they are diagnostic and disabled by default.
DEVICE_STATE_INPUTS = {
    "flowEntry": "flow_input",
    "shutterEntry": "cover_input",
    "canPhEntry": "ph_can_input",
    "cmdEntry": "command_input",
}


def is_pooltech(module: dict[str, Any]) -> bool:
    """Return True for an IPX module driving a PoolTech electrolyser."""
    return (
        str(module.get("manufacturerType", "")).upper() == MANUFACTURER_TYPE_IPX
        and module.get("typeIpx") == IPX_TYPE_POOLTECH
    )


def electrolysers(data: MyIndygoData) -> list[dict[str, Any]]:
    """Return the PoolTech IPX modules of the account."""
    return [module for module in data.cloud.data.modules.values() if is_pooltech(module)]


def output_data(module: dict[str, Any], output_type: int) -> dict[str, Any] | None:
    """Return the ``ipxData`` of the electrolyser output of a given type (pH or electrolyzer)."""
    for output in module.get("outputs", []):
        ipx = output.get("ipxData") or {}
        if ipx.get("type") == output_type:
            return ipx
    return None


def has_output(module: dict[str, Any], output_type: int) -> bool:
    return output_data(module, output_type) is not None


def input_of_type(module: dict[str, Any], input_type: int) -> dict[str, Any] | None:
    return next((item for item in module.get("inputs", []) if item.get("type") == input_type), None)


def last_value(module: dict[str, Any], input_type: int) -> float | None:
    """Latest converted measure of an input (the platform already applies the expression)."""
    item = input_of_type(module, input_type)
    value = ((item or {}).get("lastValue") or {}).get("value")
    return float(value) if isinstance(value, int | float) else None


def output_value(module: dict[str, Any], output_type: int, key: str) -> Any:
    return (output_data(module, output_type) or {}).get(key)


def device_state(module: dict[str, Any], key: str) -> bool | None:
    value = ((module.get("ipxData") or {}).get("deviceState") or {}).get(key)
    return value if isinstance(value, bool) else None


def alarms(module: dict[str, Any]) -> list[str]:
    """Active alarms of both outputs, as texts provided by the platform."""
    found: list[str] = []
    for output in module.get("outputs", []):
        found.extend(str(alarm) for alarm in (output.get("ipxData") or {}).get("stateAlarms") or [])
    return found


ModuleFn = Callable[[dict[str, Any]], Any]


class ElectrolyserEntity(MyIndygoEntity):
    """Entity of an electrolyser, refreshed by the cloud coordinator."""

    def __init__(
        self,
        data: MyIndygoData,
        module: dict[str, Any],
        key: str,
        translation_key: str,
        value_fn: ModuleFn,
    ) -> None:
        super().__init__(data.cloud, module, key, translation_key)
        self._data = data
        self._value_fn = value_fn

    @property
    def current_module(self) -> dict[str, Any] | None:
        cloud = self._data.cloud.data
        return cloud.modules.get(self.module_id) if cloud else None

    @property
    def available(self) -> bool:
        return super().available and self.current_module is not None

    def _value(self) -> Any:
        module = self.current_module
        return self._value_fn(module) if module is not None else None
