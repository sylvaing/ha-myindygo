"""Select entities of MyIndygo: electrolyser modes (pH regulation, electrolysis)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MyIndygoConfigEntry, MyIndygoData
from .electrolyser import OUTPUT_ELECTROLYZER, OUTPUT_PH_REGULATOR, electrolysers, has_output
from .ipx_settings import KEY_ELECTROLYZER_MODE, KEY_PH_MODE, IpxSettingEntity, reported_value

# Writes go to the cloud one at a time.
PARALLEL_UPDATES = 1

PH_MODE_OPTIONS = {0: "off", 1: "on"}
# Mode 2 (auto, driven by a redox or chlorine probe) needs a probe and a setpoint of its own, which
# are not supported: it is not offered (the "Electrolysis mode" sensor still reports it).
ELECTROLYSIS_MODE_OPTIONS = {0: "off", 1: "percentage"}


async def async_setup_entry(
    hass: HomeAssistant, entry: MyIndygoConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    """Set up the electrolyser modes."""
    data = entry.runtime_data
    entities: list[SelectEntity] = []
    for module in electrolysers(data):
        if has_output(module, OUTPUT_PH_REGULATOR):
            entities.append(
                IpxSelect(data, module, "ph_regulation", OUTPUT_PH_REGULATOR, KEY_PH_MODE, PH_MODE_OPTIONS)
            )
        if has_output(module, OUTPUT_ELECTROLYZER):
            entities.append(
                IpxSelect(
                    data,
                    module,
                    "electrolysis_mode",
                    OUTPUT_ELECTROLYZER,
                    KEY_ELECTROLYZER_MODE,
                    ELECTROLYSIS_MODE_OPTIONS,
                )
            )
    async_add_entities(entities)


class IpxSelect(IpxSettingEntity, SelectEntity):
    """A mode of the electrolyser: shows the reported mode, a request stays pending."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        data: MyIndygoData,
        module: dict[str, Any],
        key: str,
        output_type: int,
        setting_key: str,
        options: dict[int, str],
    ) -> None:
        super().__init__(
            data, module, f"{key}_control", key, lambda m: reported_value(m, output_type, setting_key)
        )
        self._output_type = output_type
        self._key = setting_key
        self._names = options
        self._codes = {name: code for code, name in options.items()}
        self._attr_options = list(options.values())

    @property
    def current_option(self) -> str | None:
        return self._names.get(self._value())

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        pending = (super().extra_state_attributes or {}).get("pending_value")
        return {"pending_value": self._names.get(pending, pending)}

    async def async_select_option(self, option: str) -> None:
        await self.async_write_setting(self._codes[option])
