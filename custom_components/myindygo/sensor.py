"""Sensors of MyIndygo."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfElectricPotential,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import MyIndygoConfigEntry, MyIndygoData
from .controller import (
    ControllerContext,
    ControllerEntity,
    ValueFn,
    controllers,
    output_indexes,
    output_naming,
)
from .electrolyser import (
    ELECTROLYZER_MODES,
    INPUT_PH,
    INPUT_REDOX,
    OUTPUT_ELECTROLYZER,
    OUTPUT_PH_REGULATOR,
    PH_MODES,
    ElectrolyserEntity,
    ModuleFn,
    electrolysers,
    has_output,
    input_of_type,
    last_value,
    output_value,
)
from .gateway import GatewayEntity, GatewayFn, gateways, last_restart
from .pool import (
    DEVICE_PROGRAM_TYPES,
    MODES,
    OUTPUT_STATES,
    RULES,
    device_program,
    input_value,
    output_state,
    output_status,
    planned_minutes,
    program_characteristic,
    remaining_minutes,
    temperature_band_label,
    temperature_inputs,
)

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant, entry: MyIndygoConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    """Set up the sensors."""
    data = entry.runtime_data
    entities: list[SensorEntity] = []
    for module in controllers(data):
        entities.extend(_controller_sensors(data, module))
    for module in electrolysers(data):
        entities.extend(_electrolyser_sensors(data, module))
    for module in gateways(data):
        entities.append(
            GatewaySensor(
                data,
                module,
                "last_restart",
                lambda _m, info: last_restart(info),
                device_class=SensorDeviceClass.TIMESTAMP,
            )
        )
        # Meaning of this code is not documented: kept for diagnosis, disabled by default.
        entities.append(
            GatewaySensor(
                data, module, "reset_code", lambda _m, info: (info or {}).get("reset"), enabled=False
            )
        )
    async_add_entities(entities)


def _controller_sensors(data: MyIndygoData, module: dict[str, Any]) -> list[SensorEntity]:
    entities: list[SensorEntity] = []
    temperatures = temperature_inputs(module)
    for position, cloud_input in enumerate(temperatures):
        key = "water_temperature" if position == 0 else f"temperature_{cloud_input['index']}"
        entities.append(
            ControllerSensor(
                data,
                module,
                key,
                "water_temperature" if position == 0 else "input_temperature",
                lambda ctx, inp=cloud_input: input_value(ctx.status, inp) if ctx.status else None,
                placeholders=None if position == 0 else {"number": str(cloud_input["index"])},
                device_class=SensorDeviceClass.TEMPERATURE,
                unit=UnitOfTemperature.CELSIUS,
                state_class=SensorStateClass.MEASUREMENT,
            )
        )

    for index in output_indexes(module):

        def item(ctx: ControllerContext, i: int = index) -> dict[str, Any] | None:
            return output_status(ctx.status or {}, i)

        def program(ctx: ControllerContext, i: int = index) -> dict[str, Any] | None:
            return device_program(ctx.device_programs, i)

        key, placeholders = output_naming(index, "filtration_state", "output_state")
        entities.append(
            ControllerSensor(
                data,
                module,
                f"output_{index}_state",
                key,
                lambda ctx, f=item: output_state(o) if (o := f(ctx)) else None,
                placeholders=placeholders,
                device_class=SensorDeviceClass.ENUM,
                options=OUTPUT_STATES,
            )
        )
        key, placeholders = output_naming(index, "filtration_remaining", "output_remaining")
        entities.append(
            ControllerSensor(
                data,
                module,
                f"output_{index}_remaining",
                key,
                lambda ctx, f=item: remaining_minutes(o) if (o := f(ctx)) else None,
                placeholders=placeholders,
                device_class=SensorDeviceClass.DURATION,
                unit=UnitOfTime.MINUTES,
            )
        )
        key, placeholders = output_naming(index, "filtration_mode", "output_mode")
        entities.append(
            ControllerSensor(
                data,
                module,
                f"output_{index}_mode",
                key,
                lambda ctx, f=program: program_characteristic(f(ctx), "mode", MODES),
                placeholders=placeholders,
                device_class=SensorDeviceClass.ENUM,
                options=list(MODES.values()),
            )
        )
        key, placeholders = output_naming(index, "filtration_rule", "output_rule")
        entities.append(
            ControllerSensor(
                data,
                module,
                f"output_{index}_rule",
                key,
                lambda ctx, f=program: program_characteristic(f(ctx), "rule", RULES),
                placeholders=placeholders,
                device_class=SensorDeviceClass.ENUM,
                options=list(RULES.values()),
                category=EntityCategory.DIAGNOSTIC,
            )
        )
        key, placeholders = output_naming(index, "filtration_type", "output_type")
        entities.append(
            ControllerSensor(
                data,
                module,
                f"output_{index}_type",
                key,
                lambda ctx, f=program: program_characteristic(f(ctx), "programType", DEVICE_PROGRAM_TYPES),
                placeholders=placeholders,
                device_class=SensorDeviceClass.ENUM,
                options=list(DEVICE_PROGRAM_TYPES.values()),
                category=EntityCategory.DIAGNOSTIC,
            )
        )

    def band(ctx: ControllerContext) -> int | None:
        filtration = output_status(ctx.status or {}, 0)
        return filtration.get("tempRef") if filtration else None

    entities.append(
        ControllerSensor(
            data,
            module,
            "temperature_band",
            "temperature_band",
            lambda ctx: temperature_band_label(device_program(ctx.device_programs, 0), band(ctx)),
        )
    )
    entities.append(
        ControllerSensor(
            data,
            module,
            "filtration_planned_today",
            "filtration_planned_today",
            lambda ctx: planned_minutes(
                device_program(ctx.device_programs, 0), band(ctx), dt_util.now().date()
            ),
            device_class=SensorDeviceClass.DURATION,
            unit=UnitOfTime.MINUTES,
            suggested_unit=UnitOfTime.HOURS,
        )
    )
    entities.append(
        ControllerSensor(
            data,
            module,
            "controller_temperature",
            "controller_temperature",
            lambda ctx: (ctx.status or {}).get("temperature"),
            device_class=SensorDeviceClass.TEMPERATURE,
            unit=UnitOfTemperature.CELSIUS,
            state_class=SensorStateClass.MEASUREMENT,
            category=EntityCategory.DIAGNOSTIC,
            enabled=False,
        )
    )
    entities.append(
        ControllerSensor(
            data,
            module,
            "last_communication",
            "last_communication",
            lambda ctx: _parse_time((ctx.status or {}).get("dialogTimeStamp")),
            device_class=SensorDeviceClass.TIMESTAMP,
            category=EntityCategory.DIAGNOSTIC,
        )
    )
    return entities


def _parse_time(value: Any) -> datetime | None:
    return dt_util.parse_datetime(value) if isinstance(value, str) else None


class ControllerSensor(ControllerEntity, SensorEntity):
    """A sensor of a pool controller."""

    def __init__(
        self,
        data: MyIndygoData,
        module: dict[str, Any],
        key: str,
        translation_key: str,
        value_fn: ValueFn,
        *,
        placeholders: dict[str, str] | None = None,
        device_class: SensorDeviceClass | None = None,
        unit: str | None = None,
        suggested_unit: str | None = None,
        state_class: SensorStateClass | None = None,
        options: list[str] | None = None,
        category: EntityCategory | None = None,
        enabled: bool = True,
    ) -> None:
        super().__init__(data, module, key, translation_key, placeholders)
        self._value_fn = value_fn
        self._attr_device_class = device_class
        self._attr_native_unit_of_measurement = unit
        self._attr_suggested_unit_of_measurement = suggested_unit
        self._attr_state_class = state_class
        self._attr_options = options
        self._attr_entity_category = category
        self._attr_entity_registry_enabled_default = enabled

    @property
    def native_value(self) -> Any:
        return self._value_fn(self.context)


def _electrolyser_sensors(data: MyIndygoData, module: dict[str, Any]) -> list[SensorEntity]:
    def sensor(key: str, value_fn: ModuleFn, **kwargs: Any) -> ElectrolyserSensor:
        return ElectrolyserSensor(data, module, key, key, value_fn, **kwargs)

    entities: list[SensorEntity] = []
    if input_of_type(module, INPUT_PH):
        entities.append(
            sensor(
                "ph",
                lambda m: last_value(m, INPUT_PH),
                device_class=SensorDeviceClass.PH,
                state_class=SensorStateClass.MEASUREMENT,
            )
        )
    if input_of_type(module, INPUT_REDOX):
        entities.append(
            sensor(
                "redox",
                lambda m: last_value(m, INPUT_REDOX),
                device_class=SensorDeviceClass.VOLTAGE,
                unit=UnitOfElectricPotential.MILLIVOLT,
                state_class=SensorStateClass.MEASUREMENT,
            )
        )
    if has_output(module, OUTPUT_PH_REGULATOR):
        entities.append(
            sensor(
                "ph_setpoint",
                lambda m: output_value(m, OUTPUT_PH_REGULATOR, "pHSetpoint"),
                device_class=SensorDeviceClass.PH,
            )
        )
        entities.append(
            sensor(
                "ph_regulation_mode",
                lambda m: PH_MODES.get(output_value(m, OUTPUT_PH_REGULATOR, "pHMode")),
                device_class=SensorDeviceClass.ENUM,
                options=list(PH_MODES.values()),
            )
        )
    if has_output(module, OUTPUT_ELECTROLYZER):
        entities.append(
            sensor(
                "salt",
                lambda m: output_value(m, OUTPUT_ELECTROLYZER, "saltValue"),
                unit="g/L",
                state_class=SensorStateClass.MEASUREMENT,
            )
        )
        entities.append(
            sensor(
                "production_setpoint",
                lambda m: output_value(m, OUTPUT_ELECTROLYZER, "percentageSetpoint"),
                unit=PERCENTAGE,
            )
        )
        entities.append(
            sensor(
                "electrolysis_mode",
                lambda m: ELECTROLYZER_MODES.get(output_value(m, OUTPUT_ELECTROLYZER, "electrolyzerMode")),
                device_class=SensorDeviceClass.ENUM,
                options=list(ELECTROLYZER_MODES.values()),
            )
        )
        entities.append(
            sensor(
                "boost_remaining",
                lambda m: output_value(m, OUTPUT_ELECTROLYZER, "boostRemainingTime"),
                device_class=SensorDeviceClass.DURATION,
                unit=UnitOfTime.MINUTES,
            )
        )
    entities.append(
        sensor(
            "electrolysis_hours",
            lambda m: (m.get("ipxData") or {}).get("totalElectrolyseDuration"),
            device_class=SensorDeviceClass.DURATION,
            unit=UnitOfTime.HOURS,
            state_class=SensorStateClass.TOTAL_INCREASING,
            category=EntityCategory.DIAGNOSTIC,
        )
    )
    # Unit not documented (probably volts): exposed without unit rather than with a wrong one.
    entities.append(
        sensor(
            "cell_voltage",
            lambda m: (m.get("ipxData") or {}).get("cellVoltage"),
            state_class=SensorStateClass.MEASUREMENT,
            category=EntityCategory.DIAGNOSTIC,
        )
    )
    entities.append(
        sensor(
            "last_report",
            lambda m: _parse_time(m.get("lastIpxCommunication")),
            device_class=SensorDeviceClass.TIMESTAMP,
            category=EntityCategory.DIAGNOSTIC,
        )
    )
    return entities


class ElectrolyserSensor(ElectrolyserEntity, SensorEntity):
    """A sensor of an electrolyser."""

    def __init__(
        self,
        data: MyIndygoData,
        module: dict[str, Any],
        key: str,
        translation_key: str,
        value_fn: ModuleFn,
        *,
        device_class: SensorDeviceClass | None = None,
        unit: str | None = None,
        state_class: SensorStateClass | None = None,
        options: list[str] | None = None,
        category: EntityCategory | None = None,
    ) -> None:
        super().__init__(data, module, key, translation_key, value_fn)
        self._attr_device_class = device_class
        self._attr_native_unit_of_measurement = unit
        self._attr_state_class = state_class
        self._attr_options = options
        self._attr_entity_category = category

    @property
    def native_value(self) -> Any:
        return self._value()


class GatewaySensor(GatewayEntity, SensorEntity):
    """A diagnostic sensor of a gateway."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        data: MyIndygoData,
        module: dict[str, Any],
        key: str,
        value_fn: GatewayFn,
        *,
        device_class: SensorDeviceClass | None = None,
        enabled: bool = True,
    ) -> None:
        super().__init__(data, module, key, value_fn, needs_info=True)
        self._attr_device_class = device_class
        self._attr_entity_registry_enabled_default = enabled

    @property
    def native_value(self) -> Any:
        return self._value()
