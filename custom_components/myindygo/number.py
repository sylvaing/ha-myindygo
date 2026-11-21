"""Number entities of MyIndygo: electrolyser setpoints (pH, production)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MyIndygoConfigEntry, MyIndygoData
from .electrolyser import OUTPUT_ELECTROLYZER, OUTPUT_PH_REGULATOR, electrolysers, has_output
from .ipx_settings import (
    KEY_PERCENTAGE_SETPOINT,
    KEY_PH_SETPOINT,
    PH_SETPOINT_MAX,
    PH_SETPOINT_MIN,
    PH_SETPOINT_STEP,
    PRODUCTION_MAX,
    PRODUCTION_MIN,
    IpxSettingEntity,
    production_step,
    reported_value,
)

# Writes go to the cloud one at a time.
PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant, entry: MyIndygoConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    """Set up the electrolyser setpoints."""
    data = entry.runtime_data
    entities: list[NumberEntity] = []
    for module in electrolysers(data):
        if has_output(module, OUTPUT_PH_REGULATOR):
            entities.append(
                IpxNumber(
                    data,
                    module,
                    "ph_setpoint",
                    OUTPUT_PH_REGULATOR,
                    KEY_PH_SETPOINT,
                    (PH_SETPOINT_MIN, PH_SETPOINT_MAX, PH_SETPOINT_STEP),
                    device_class=NumberDeviceClass.PH,
                )
            )
        if has_output(module, OUTPUT_ELECTROLYZER):
            entities.append(
                IpxNumber(
                    data,
                    module,
                    "production_setpoint",
                    OUTPUT_ELECTROLYZER,
                    KEY_PERCENTAGE_SETPOINT,
                    (PRODUCTION_MIN, PRODUCTION_MAX, production_step(module)),
                    unit=PERCENTAGE,
                )
            )
    async_add_entities(entities)


class IpxNumber(IpxSettingEntity, NumberEntity):
    """A setpoint of the electrolyser: shows the reported value, a request stays pending."""

    _attr_entity_category = EntityCategory.CONFIG
    # A box rather than a slider: every change is a write to the electrolyser.
    _attr_mode = NumberMode.BOX

    def __init__(
        self,
        data: MyIndygoData,
        module: dict[str, Any],
        key: str,
        output_type: int,
        setting_key: str,
        limits: tuple[float, float, float],
        *,
        device_class: NumberDeviceClass | None = None,
        unit: str | None = None,
    ) -> None:
        # Same translation key as the read-only sensor, distinct unique id.
        super().__init__(
            data, module, f"{key}_control", key, lambda m: reported_value(m, output_type, setting_key)
        )
        self._output_type = output_type
        self._key = setting_key
        self._attr_native_min_value, self._attr_native_max_value, self._attr_native_step = limits
        self._attr_device_class = device_class
        self._attr_native_unit_of_measurement = unit

    @property
    def native_value(self) -> float | None:
        value = self._value()
        return value if isinstance(value, int | float) and not isinstance(value, bool) else None

    async def async_set_native_value(self, value: float) -> None:
        await self.async_write_setting(value)
