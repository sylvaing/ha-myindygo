"""Selects of MyIndygo: program mode of the controller outputs and daily filtration adjustment."""

from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MyIndygoConfigEntry, MyIndygoData
from .controller import ControllerEntity, controllers, output_indexes, output_naming
from .pool import MODES, device_program
from .programs import (
    DAILY_ADJUSTMENT_HOURS,
    MODE_VALUES,
    async_write_program,
    current_adapt_offset,
    daily_adjustment_supported,
)

# Writes go through the cloud and the radio link: one at a time.
PARALLEL_UPDATES = 1

FILTRATION_INDEX = 0


def adjustment_option(hours: int) -> str:
    """Option key of a daily adjustment: ``minus_2``, ``standard``, ``plus_1``…"""
    if hours == 0:
        return "standard"
    return f"{'plus' if hours > 0 else 'minus'}_{abs(hours)}"


ADJUSTMENT_OPTIONS = {adjustment_option(hours): hours * 60 for hours in DAILY_ADJUSTMENT_HOURS}


async def async_setup_entry(
    hass: HomeAssistant, entry: MyIndygoConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    """Set up the selects."""
    data = entry.runtime_data
    entities: list[SelectEntity] = []
    for module in controllers(data):
        indexes = output_indexes(module)
        for index in indexes:
            key, placeholders = output_naming(index, "filtration_mode", "output_mode")
            entities.append(ProgramModeSelect(data, module, index, key, placeholders))
        if FILTRATION_INDEX in indexes:
            entities.append(DailyAdjustmentSelect(data, module))
    async_add_entities(entities)


class ProgramSelect(ControllerEntity, SelectEntity):
    """A setting of an output program, written to the platform and the controller."""

    output_index: int

    def _programs(self) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """Platform and compiled copies of this output's program."""
        cloud = self._data.cloud.data
        platform = device_program(cloud.programs.get(self.module_id), self.output_index) if cloud else None
        return platform, device_program(self.context.device_programs, self.output_index)

    @property
    def available(self) -> bool:
        return super().available and self.current_option is not None


class ProgramModeSelect(ProgramSelect):
    """Mode of an output program: off, on (permanent) or auto (follows its schedule)."""

    _attr_options = list(MODE_VALUES)

    def __init__(
        self,
        data: MyIndygoData,
        module: dict[str, Any],
        index: int,
        translation_key: str,
        placeholders: dict[str, str] | None,
    ) -> None:
        super().__init__(data, module, f"output_{index}_program_mode", translation_key, placeholders)
        self.output_index = index

    @property
    def current_option(self) -> str | None:
        # The compiled program is what the controller really runs.
        _platform, device = self._programs()
        return MODES.get(((device or {}).get("programCharacteristics") or {}).get("mode"))

    async def async_select_option(self, option: str) -> None:
        await async_write_program(
            self.hass, self._data, self.module_id, self.output_index, mode=MODE_VALUES[option]
        )


class DailyAdjustmentSelect(ProgramSelect):
    """Daily adjustment of a thermo-adaptive filtration (*Standard −4 h … +4 h* in the app)."""

    _attr_options = list(ADJUSTMENT_OPTIONS)
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, data: MyIndygoData, module: dict[str, Any]) -> None:
        super().__init__(data, module, "filtration_daily_adjustment", "filtration_daily_adjustment")
        self.output_index = FILTRATION_INDEX

    @property
    def current_option(self) -> str | None:
        platform, device = self._programs()
        if not daily_adjustment_supported(platform, device):
            return None
        offset = current_adapt_offset(platform)
        return next((key for key, value in ADJUSTMENT_OPTIONS.items() if value == offset), None)

    async def async_select_option(self, option: str) -> None:
        await async_write_program(
            self.hass,
            self._data,
            self.module_id,
            self.output_index,
            adapt_offset=ADJUSTMENT_OPTIONS[option],
        )
