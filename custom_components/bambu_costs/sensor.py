"""Derived sensors for Bambu Print Costs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.restore_state import ExtraStoredData, RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_PRINT_WEIGHT, DOMAIN, URL_COVERS
from .coordinator import BambuCostsCoordinator


@dataclass
class BreakdownSnapshot(ExtraStoredData):
    """The last per-slot split, stored so it survives a restart."""

    snapshot: dict[str, Any] | None

    def as_dict(self) -> dict[str, Any]:
        return {"snapshot": self.snapshot}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: BambuCostsCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            FilamentBreakdownSensor(coordinator),
            SessionFilamentCostSensor(coordinator),
            TagLibrarySensor(coordinator),
            JobLogSensor(coordinator),
        ]
    )


class BambuCostsSensor(CoordinatorEntity[BambuCostsCoordinator], SensorEntity):
    """Shared plumbing."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator: BambuCostsCoordinator, key: str, name: str) -> None:
        super().__init__(coordinator)
        self._key = key
        self._attr_name = name
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{key}"
        self._attr_device_info = coordinator.device_info


class FilamentBreakdownSensor(BambuCostsSensor, RestoreEntity):
    """Per-slot filament usage and cost for the job on the printer right now.

    State is the total filament cost. The per-slot rows live in the ``slots``
    attribute, unrounded, so consumers round once at their own display point.
    """

    _attr_native_unit_of_measurement = "EUR"
    _attr_icon = "mdi:table-split-cell"
    _attr_suggested_display_precision = 4

    def __init__(self, coordinator: BambuCostsCoordinator) -> None:
        super().__init__(coordinator, "filament_breakdown", "Filament breakdown")
        self._data: dict[str, Any] = coordinator.breakdown()

    @property
    def extra_restore_state_data(self) -> BreakdownSnapshot:
        """Persist the last real per-slot split across restarts."""
        return BreakdownSnapshot(self.coordinator.last_good)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        # Seed the snapshot before anything recomputes, so a restart taken
        # mid-print does not briefly publish a repriced External row.
        stored = await self.async_get_last_extra_data()
        if stored is not None:
            snapshot = stored.as_dict().get("snapshot")
            if isinstance(snapshot, dict) and snapshot.get("slots"):
                self.coordinator.last_good = snapshot

        # The breakdown is derived from another entity's attributes, so it has
        # to follow that entity as well as the coordinator's price changes.
        source = self.coordinator.entity_of(CONF_PRINT_WEIGHT)
        if source:
            self.async_on_remove(
                async_track_state_change_event(self.hass, [source], self._source_changed)
            )
        self._recompute()

    @callback
    def _source_changed(self, _event: Any) -> None:
        self._recompute()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._recompute()

    @callback
    def _recompute(self) -> None:
        self._data = self.coordinator.breakdown()
        self.async_write_ha_state()

    @property
    def native_value(self) -> float:
        return round(self._data["cost"], 4)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "slots": self._data["slots"],
            "weight": self._data["weight"],
            "weight_total": self._data["weight_total"],
            "source": self._data["source"],
            # True when the printer stopped reporting per-slot weights and the
            # remembered split is standing in for them.
            "restored": self._data.get("restored", False),
        }


class SessionFilamentCostSensor(BambuCostsSensor):
    """Display-rounded twin of the breakdown cost."""

    _attr_native_unit_of_measurement = "EUR"
    _attr_icon = "mdi:cash"
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator: BambuCostsCoordinator) -> None:
        super().__init__(coordinator, "session_filament_cost", "Session filament cost")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        source = self.coordinator.entity_of(CONF_PRINT_WEIGHT)
        if source:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass, [source], lambda _e: self.async_write_ha_state()
                )
            )

    @property
    def native_value(self) -> float:
        return round(self.coordinator.breakdown()["cost"], 2)


class TagLibrarySensor(BambuCostsSensor):
    """The filament tag library. State is the row count so it always changes."""

    _attr_icon = "mdi:tag-multiple"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: BambuCostsCoordinator) -> None:
        super().__init__(coordinator, "tag_library", "Tag library")

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data.get("tags", []))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        tags = self.coordinator.data.get("tags", [])
        return {
            "data": tags,
            "enabled_count": sum(1 for t in tags if not t.get("disabled")),
        }


class JobLogSensor(BambuCostsSensor):
    """Logged print jobs, newest last."""

    _attr_icon = "mdi:history"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: BambuCostsCoordinator) -> None:
        super().__init__(coordinator, "job_log", "Job log")

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data.get("jobs", []))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        entry_id = self.coordinator.entry.entry_id
        jobs = []
        for job in self.coordinator.data.get("jobs", []):
            row = dict(job)
            cover = row.get("cover")
            row["cover_url"] = (
                f"{URL_COVERS}/{entry_id}/covers/{cover}" if cover else ""
            )
            jobs.append(row)
        return {"data": jobs}
