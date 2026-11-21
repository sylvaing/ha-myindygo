"""Button entities of MyIndygo: electrolyser boost (12 h, 24 h, stop).

Buttons rather than a select: the electrolyser only reports whether a boost runs and its remaining
time, not the duration that was requested, so a select would have to guess its current option.
The state of the boost is in the ``Boost`` binary sensor and the ``Boost remaining time`` sensor.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MyIndygoConfigEntry, MyIndygoData
from .electrolyser import OUTPUT_ELECTROLYZER, electrolysers, has_output
from .ipx_settings import KEY_BOOST_COMMAND, IpxSettingEntity, reported_value

# Writes go to the cloud one at a time.
PARALLEL_UPDATES = 1

# entity key -> boostCommand value
BOOST_BUTTONS = {"boost_12h": 12, "boost_24h": 24, "boost_stop": 0}


async def async_setup_entry(
    hass: HomeAssistant, entry: MyIndygoConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    """Set up the boost buttons."""
    data = entry.runtime_data
    async_add_entities(
        IpxBoostButton(data, module, key, command)
        for module in electrolysers(data)
        if has_output(module, OUTPUT_ELECTROLYZER)
        for key, command in BOOST_BUTTONS.items()
    )


class IpxBoostButton(IpxSettingEntity, ButtonEntity):
    """Request a boost of the electrolyser (or stop it); it is pending until the device takes it."""

    _attr_entity_category = EntityCategory.CONFIG
    _output_type = OUTPUT_ELECTROLYZER
    _key = KEY_BOOST_COMMAND

    def __init__(self, data: MyIndygoData, module: dict[str, Any], key: str, command: int) -> None:
        super().__init__(
            data, module, key, key, lambda m: reported_value(m, OUTPUT_ELECTROLYZER, "boostEnabled")
        )
        self._command = command

    async def async_press(self) -> None:
        running = self._command != 0
        await self.async_write_setting(
            self._command,
            lambda m: reported_value(m, OUTPUT_ELECTROLYZER, "boostEnabled") is running,
        )
