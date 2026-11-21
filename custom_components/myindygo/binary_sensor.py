"""Binary sensors of MyIndygo."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MyIndygoConfigEntry, MyIndygoData
from .commands import OutputCommandEntity
from .controller import ControllerEntity, ValueFn, controllers, output_indexes, output_naming
from .electrolyser import (
    DEVICE_STATE_INPUTS,
    OUTPUT_ELECTROLYZER,
    ElectrolyserEntity,
    ModuleFn,
    alarms,
    device_state,
    electrolysers,
    has_output,
    output_value,
)
from .gateway import GatewayEntity, GatewayFn, gateways
from .ipx_settings import all_pending
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
            entities.append(OutputBinarySensor(data, module, index, key, placeholders))
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
    for module in electrolysers(data):
        entities.extend(_electrolyser_binary_sensors(data, module))
    for module in gateways(data):
        entities.append(
            GatewayBinarySensor(
                data,
                module,
                "cloud_connection",
                lambda m, _info: m.get("isOnline"),
                device_class=BinarySensorDeviceClass.CONNECTIVITY,
            )
        )
        entities.append(
            GatewayBinarySensor(
                data,
                module,
                "wifi_link",
                lambda _m, info: (info or {}).get("wifiLink"),
                device_class=BinarySensorDeviceClass.CONNECTIVITY,
                category=EntityCategory.DIAGNOSTIC,
                needs_info=True,
            )
        )
    async_add_entities(entities)


class GatewayBinarySensor(GatewayEntity, BinarySensorEntity):
    """A binary sensor of a gateway."""

    def __init__(
        self,
        data: MyIndygoData,
        module: dict[str, Any],
        key: str,
        value_fn: GatewayFn,
        *,
        device_class: BinarySensorDeviceClass | None = None,
        category: EntityCategory | None = None,
        needs_info: bool = False,
    ) -> None:
        super().__init__(data, module, key, value_fn, needs_info=needs_info)
        self._attr_device_class = device_class
        self._attr_entity_category = category

    @property
    def is_on(self) -> bool | None:
        value = self._value()
        return value if isinstance(value, bool) else None


def _electrolyser_binary_sensors(data: MyIndygoData, module: dict[str, Any]) -> list[BinarySensorEntity]:
    def sensor(key: str, value_fn: ModuleFn, **kwargs: Any) -> ElectrolyserBinarySensor:
        return ElectrolyserBinarySensor(data, module, key, key, value_fn, **kwargs)

    entities: list[BinarySensorEntity] = [
        sensor(
            "production",
            lambda m: device_state(m, "prodStatus"),
            device_class=BinarySensorDeviceClass.RUNNING,
        ),
        sensor(
            "ph_injection",
            lambda m: device_state(m, "pHInjection"),
            device_class=BinarySensorDeviceClass.RUNNING,
        ),
        sensor("wintering", _wintered),
        ElectrolyserAlarmSensor(data, module, "alarm", "alarm", lambda m: bool(alarms(m))),
        ElectrolyserPendingSensor(
            data, module, "settings_pending", "settings_pending", lambda m: bool(all_pending(m))
        ),
    ]
    if has_output(module, OUTPUT_ELECTROLYZER):
        entities.append(sensor("boost", lambda m: output_value(m, OUTPUT_ELECTROLYZER, "boostEnabled")))
    for state_key, key in DEVICE_STATE_INPUTS.items():
        entities.append(
            sensor(
                key,
                lambda m, k=state_key: device_state(m, k),
                category=EntityCategory.DIAGNOSTIC,
                enabled=False,
            )
        )
    return entities


def _wintered(module: dict[str, Any]) -> bool | None:
    values = [
        (output.get("ipxData") or {}).get("isWintered")
        for output in module.get("outputs", [])
        if isinstance((output.get("ipxData") or {}).get("isWintered"), bool)
    ]
    return any(values) if values else None


class ElectrolyserBinarySensor(ElectrolyserEntity, BinarySensorEntity):
    """A binary sensor of an electrolyser."""

    def __init__(
        self,
        data: MyIndygoData,
        module: dict[str, Any],
        key: str,
        translation_key: str,
        value_fn: ModuleFn,
        *,
        device_class: BinarySensorDeviceClass | None = None,
        category: EntityCategory | None = None,
        enabled: bool = True,
    ) -> None:
        super().__init__(data, module, key, translation_key, value_fn)
        self._attr_device_class = device_class
        self._attr_entity_category = category
        self._attr_entity_registry_enabled_default = enabled

    @property
    def is_on(self) -> bool | None:
        value = self._value()
        return value if isinstance(value, bool) else None


class ElectrolyserAlarmSensor(ElectrolyserBinarySensor):
    """On when the electrolyser reports an alarm; the texts are in the ``alarms`` attribute."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, device_class=BinarySensorDeviceClass.PROBLEM, **kwargs)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        module = self.current_module
        return {"alarms": alarms(module) if module else []}


class ElectrolyserPendingSensor(ElectrolyserBinarySensor):
    """On while a setting waits for the electrolyser; the requests are in the ``pending`` attribute."""

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        module = self.current_module
        return {"pending": all_pending(module) if module else {}}


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


class OutputBinarySensor(ControllerBinarySensor, OutputCommandEntity):
    """Running state of a controller output; target of the manual command actions."""

    def __init__(
        self,
        data: MyIndygoData,
        module: dict[str, Any],
        index: int,
        translation_key: str,
        placeholders: dict[str, str] | None,
    ) -> None:
        super().__init__(
            data,
            module,
            f"output_{index}_running",
            translation_key,
            lambda ctx: _running(ctx.status, index),
            placeholders=placeholders,
            device_class=BinarySensorDeviceClass.RUNNING,
        )
        self.output_index = index


def _running(status: dict[str, Any] | None, index: int) -> bool | None:
    item = output_status(status or {}, index)
    return bool(item.get("value")) if item else None
