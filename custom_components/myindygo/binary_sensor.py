"""Binary sensors of MyIndygo."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MyIndygoConfigEntry, MyIndygoData
from .controller import ControllerEntity, ValueFn, controllers, output_indexes, output_naming
from .pool import output_status

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant, entry: MyIndygoConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    """Set up the binary sensors."""
    data = entry.runtime_data
    entities: list[BinarySensorEntity] = []
    for module in controllers(data):
        for index in output_indexes(module):
            key, placeholders = output_naming(index, "filtration_running", "output_running")
            entities.append(
                ControllerBinarySensor(
                    data,
                    module,
                    f"output_{index}_running",
                    key,
                    lambda ctx, i=index: (
                        bool(o.get("value")) if (o := output_status(ctx.status or {}, i)) else None
                    ),
                    placeholders=placeholders,
                    device_class=BinarySensorDeviceClass.RUNNING,
                )
            )
        entities.append(
            ControllerBinarySensor(
                data,
                module,
                "radio_pending",
                "radio_pending",
                lambda ctx: bool((ctx.status or {}).get("radio")),
                category=EntityCategory.DIAGNOSTIC,
            )
        )
        entities.append(
            ControllerBinarySensor(
                data,
                module,
                "input_alert",
                "input_alert",
                lambda ctx: bool((ctx.status or {}).get("inputsAlerts")),
                device_class=BinarySensorDeviceClass.PROBLEM,
            )
        )
    async_add_entities(entities)


class ControllerBinarySensor(ControllerEntity, BinarySensorEntity):
    """A binary sensor of a pool controller."""

    def __init__(
        self,
        data: MyIndygoData,
        module: dict[str, Any],
        key: str,
        translation_key: str,
        value_fn: ValueFn,
        *,
        placeholders: dict[str, str] | None = None,
        device_class: BinarySensorDeviceClass | None = None,
        category: EntityCategory | None = None,
    ) -> None:
        super().__init__(data, module, key, translation_key, placeholders)
        self._value_fn = value_fn
        self._attr_device_class = device_class
        self._attr_entity_category = category

    @property
    def is_on(self) -> bool | None:
        return self._value_fn(self.context)


def _running(status: dict[str, Any] | None, index: int) -> bool | None:
    item = output_status(status or {}, index)
    return bool(item.get("value")) if item else None
