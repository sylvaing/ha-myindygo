"""Base entity for MyIndygo."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator

from .const import DOMAIN


class MyIndygoEntity(CoordinatorEntity[DataUpdateCoordinator[Any]]):
    """An entity attached to one MyIndygo module (one Home Assistant device)."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DataUpdateCoordinator[Any],
        module: dict[str, Any],
        key: str,
        translation_key: str,
        placeholders: dict[str, str] | None = None,
    ) -> None:
        super().__init__(coordinator)
        self.module_id: str = module["id"]
        self._attr_unique_id = f"{module['serialNumber']}_{key}"
        self._attr_translation_key = translation_key
        if placeholders:
            self._attr_translation_placeholders = placeholders
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, module["serialNumber"])})
