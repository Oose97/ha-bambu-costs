"""Choices that flip at runtime rather than living in the options flow."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_CAMERA, CONF_FILAMENT_INVENTORY, DOMAIN
from .coordinator import BambuCostsCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: BambuCostsCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SwitchEntity] = [MaintenanceModeSwitch(coordinator)]
    # Pointless without a camera to snapshot. Adding one later reloads the
    # entry, which lands back here and creates the switch.
    if coordinator.entity_of(CONF_CAMERA):
        entities.append(CameraCoverSwitch(coordinator))
    # Only meaningful WITH a cloud inventory — without one the on-load
    # figure is taken unconditionally, there being nothing to overwrite.
    if coordinator.entity_of(CONF_FILAMENT_INVENTORY):
        entities.append(LoadRemainingSwitch(coordinator))
    async_add_entities(entities)


class CameraCoverSwitch(
    CoordinatorEntity[BambuCostsCoordinator], SwitchEntity, RestoreEntity
):
    """Photograph the finished print instead of storing the slicer's render.

    A switch rather than a config option because it is worth flipping per
    job — the render identifies a model, the photo records how the print
    actually came out.
    """

    _attr_has_entity_name = True
    _attr_name = "Use camera snapshot"
    _attr_icon = "mdi:camera"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_should_poll = False

    def __init__(self, coordinator: BambuCostsCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_use_camera_cover"
        self._attr_device_info = coordinator.device_info

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None:
            self.coordinator.use_camera_cover = last.state == "on"
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool:
        return self.coordinator.use_camera_cover

    async def async_turn_on(self, **kwargs: Any) -> None:
        self.coordinator.use_camera_cover = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.coordinator.use_camera_cover = False
        self.async_write_ha_state()


class LoadRemainingSwitch(
    CoordinatorEntity[BambuCostsCoordinator], SwitchEntity, RestoreEntity
):
    """Take the tray's remaining % the moment a spool is loaded.

    The cloud inventory is the source of truth for remaining grams, but it
    only moves on the cloud's own bookkeeping events. With this on, loading
    a spool writes the tray's reported % right away — as grams of an
    assumed 1 kg spool — and the next inventory reading overwrites it.
    Only offered when an inventory sensor is configured; without one the
    on-load figure is taken unconditionally.
    """

    _attr_has_entity_name = True
    _attr_name = "Always take remaining on load"
    _attr_icon = "mdi:chart-donut"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_should_poll = False

    def __init__(self, coordinator: BambuCostsCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_load_remaining"
        self._attr_device_info = coordinator.device_info

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None:
            self.coordinator.load_remaining = last.state == "on"
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool:
        return self.coordinator.load_remaining

    async def async_turn_on(self, **kwargs: Any) -> None:
        self.coordinator.load_remaining = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.coordinator.load_remaining = False
        self.async_write_ha_state()


class MaintenanceModeSwitch(
    CoordinatorEntity[BambuCostsCoordinator], SwitchEntity, RestoreEntity
):
    """Log upkeep prints as electricity only.

    Calibration lines, flow tests, a cleaning blob — runs whose filament is
    not worth billing to any spool. While this is on, a logged job carries
    the name "Maintenance", its duration, energy and electricity, and
    nothing else: no filament figures, no per-slot rows, no picture.
    Everything live — slot prices, tag scanning, the session sensors — keeps
    working; only what reaches the log changes.
    """

    _attr_has_entity_name = True
    _attr_name = "Maintenance mode"
    _attr_icon = "mdi:wrench-clock"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_should_poll = False

    def __init__(self, coordinator: BambuCostsCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_maintenance_mode"
        self._attr_device_info = coordinator.device_info

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None:
            self.coordinator.maintenance = last.state == "on"
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool:
        return self.coordinator.maintenance

    async def async_turn_on(self, **kwargs: Any) -> None:
        self.coordinator.maintenance = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.coordinator.maintenance = False
        self.async_write_ha_state()
