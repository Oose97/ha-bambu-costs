"""Derived sensors for Bambu Print Costs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from homeassistant.components.sensor import RestoreSensor, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.restore_state import ExtraStoredData, RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .colors import COLOR_NAME_OPTIONS
from .const import (
    CONF_COVER_IMAGE,
    CONF_DEFAULT_FILAMENT_PRICE,
    CONF_ELECTRICITY_PRICE_ENTITY,
    CONF_FILAMENT_TYPES,
    CONF_POWER_SENSORS,
    COST_TICK_SECONDS,
    CONF_PRINT_WEIGHT,
    DEFAULT_FILAMENT_TYPES,
    DOMAIN,
    URL_COVERS,
)
from .coordinator import BambuCostsCoordinator
from .storage import count_spools


@dataclass
class BreakdownSnapshot(ExtraStoredData):
    """The last per-slot split, stored so it survives a restart.

    ``slots`` rides along: what each slot was printing from, so a restart
    followed by a spool running out still costs the job at what it was
    actually printed with. Absent in data stored before it existed.
    """

    snapshot: dict[str, Any] | None
    slots: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"snapshot": self.snapshot, "slots": self.slots}


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
            SessionPowerCostSensor(coordinator),
            CostRateSensor(coordinator),
            CostTotalSensor(coordinator),
            SpendTotalSensor(coordinator),
            TagLibrarySensor(coordinator),
            SpoolCountSensor(coordinator, "spools", "Spools", active_only=False),
            SpoolCountSensor(coordinator, "active_spools", "Active spools", active_only=True),
            JobLogSensor(coordinator),
            CurrentJobSensor(coordinator),
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

    _attr_icon = "mdi:table-split-cell"
    _attr_suggested_display_precision = 4

    def __init__(self, coordinator: BambuCostsCoordinator) -> None:
        super().__init__(coordinator, "filament_breakdown", "Filament breakdown")
        self._attr_native_unit_of_measurement = coordinator.currency
        self._data: dict[str, Any] = coordinator.breakdown()

    @property
    def extra_restore_state_data(self) -> BreakdownSnapshot:
        """Persist the last real per-slot split across restarts."""
        return BreakdownSnapshot(
            self.coordinator.last_good, self.coordinator.slot_memory
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        # Seed the snapshot before anything recomputes, so a restart taken
        # mid-print does not briefly publish a repriced External row.
        stored = await self.async_get_last_extra_data()
        if stored is not None:
            data = stored.as_dict()
            snapshot = data.get("snapshot")
            if isinstance(snapshot, dict) and snapshot.get("slots"):
                self.coordinator.last_good = snapshot
            slots = data.get("slots")
            if isinstance(slots, dict):
                self.coordinator.slot_memory = slots

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
        # Not _recompute(): that notifies the coordinator, and being called
        # from a coordinator notification would loop.
        self._data = self.coordinator.breakdown()
        self.async_write_ha_state()

    @callback
    def _recompute(self) -> None:
        self._data = self.coordinator.breakdown()
        self.async_write_ha_state()
        # Everything else derived from the breakdown has to hear about this.
        # The coordinator only notifies on its own refresh and on a value
        # change, so a restored snapshot or a print-weight update would
        # otherwise leave the session cost showing whatever it had at startup.
        self.coordinator.async_update_listeners()

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

    _attr_icon = "mdi:cash"
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator: BambuCostsCoordinator) -> None:
        super().__init__(coordinator, "session_filament_cost", "Session filament cost")
        self._attr_native_unit_of_measurement = coordinator.currency

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
        # A display read must not be what updates the restart snapshot.
        return round(self.coordinator.breakdown(remember=False)["cost"], 2)


class SessionPowerCostSensor(BambuCostsSensor):
    """What the print on the printer has cost in electricity, so far.

    Live while a print runs — the same integral the finished job will be
    charged — and the finished print's figure once it ends, until the next
    one starts. The legacy stacks this replaces kept it in a utility_meter
    that an automation had to calibrate at every start and finish.
    """

    _attr_icon = "mdi:flash"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 4

    def __init__(self, coordinator: BambuCostsCoordinator) -> None:
        super().__init__(coordinator, "session_power_cost", "Session power cost")
        self._attr_native_unit_of_measurement = coordinator.currency

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # Its own tick, like the cost total's: the value moves with elapsed
        # time even when no watched entity changes state.
        self.async_on_remove(
            async_track_time_interval(
                self.hass, self._tick, timedelta(seconds=COST_TICK_SECONDS)
            )
        )

    @callback
    def _tick(self, _now: Any) -> None:
        self.coordinator.accrue_cost()
        self.async_write_ha_state()

    @property
    def native_value(self) -> float:
        if self.coordinator.print_running:
            return round(self.coordinator.spend_since("cost_at_print_start"), 6)
        return round(self.coordinator.value("last_print_power_cost"), 6)


class CostRateSensor(BambuCostsSensor):
    """What the machine is costing per hour, right now."""

    _attr_icon = "mdi:speedometer"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 4

    def __init__(self, coordinator: BambuCostsCoordinator) -> None:
        super().__init__(coordinator, "cost_rate", "Cost rate")
        self._attr_native_unit_of_measurement = f"{coordinator.currency}/h"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        watched = list(self.coordinator.options.get(CONF_POWER_SENSORS) or [])
        price_entity = self.coordinator.entity_of(CONF_ELECTRICITY_PRICE_ENTITY)
        if price_entity:
            watched.append(price_entity)
        if watched:
            self.async_on_remove(
                async_track_state_change_event(self.hass, watched, self._changed)
            )

    @callback
    def _changed(self, _event: Any) -> None:
        # Charge the interval just ended at the rate that applied to it before
        # picking up the new one.
        self.coordinator.accrue_cost()
        self.async_write_ha_state()

    @property
    def native_value(self) -> float:
        return round(self.coordinator.cost_rate(), 6)


class CostTotalSensor(BambuCostsSensor, RestoreSensor):
    """Everything the machine has cost to run, printing or idle.

    Restored across restarts, and settable in one direction only — it is the
    integral of the rate, so it never goes down.
    """

    _attr_icon = "mdi:cash-clock"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_suggested_display_precision = 4

    def __init__(self, coordinator: BambuCostsCoordinator) -> None:
        super().__init__(coordinator, "cost_total", "Cost total")
        self._attr_native_unit_of_measurement = coordinator.currency

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        restored = await self.async_get_last_sensor_data()
        if restored is not None and restored.native_value is not None:
            try:
                self.coordinator.cost_total = float(restored.native_value)
            except (TypeError, ValueError):
                pass

        # Seed the rate so the first tick charges from now, not from epoch.
        self.coordinator.accrue_cost()

        self.async_on_remove(
            async_track_time_interval(
                self.hass, self._tick, timedelta(seconds=COST_TICK_SECONDS)
            )
        )

    @callback
    def _tick(self, _now: Any) -> None:
        self.coordinator.accrue_cost()
        self.async_write_ha_state()

    @property
    def native_value(self) -> float:
        return round(self.coordinator.cost_total, 6)


class SpendTotalSensor(BambuCostsSensor):
    """Everything the printer has cost, filament included.

    A mirror of the ``total_cost`` number, which is where the running figure
    actually lives — that one has to stay a number so it can be seeded when
    cutting over from an older setup, and numbers carry no state class, so
    nothing downstream will meter or graph them.

    This exists to be that downstream source. Point a `utility_meter` at it for
    a monthly figure: cycles, restarts and DST are core's problem then, not
    this integration's, and you can have daily and yearly off the same sensor
    without any of it being reimplemented here.

    ``cost_total`` is the narrower one — electricity only. This is the whole
    bill: filament, electricity, and standby between jobs.
    """

    _attr_icon = "mdi:cash-multiple"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator: BambuCostsCoordinator) -> None:
        super().__init__(coordinator, "total_spend", "Total spend")
        self._attr_native_unit_of_measurement = coordinator.currency

    @property
    def native_value(self) -> float | None:
        # The value lives in the total_cost number and only exists once that
        # entity has restored. Platforms set up concurrently, so this sensor
        # can render first — and publishing 0 then would read as a meter reset
        # to long-term statistics, silently adding the whole balance to
        # whatever utility_meter is watching. Unknown is skipped by statistics;
        # 0 is believed.
        if "total_cost" not in self.coordinator.values:
            return None
        return round(self.coordinator.value("total_cost"), 4)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        # Split out so a dashboard can show where the money went without
        # needing to read three separate entities.
        return {
            "filament_total": round(self.coordinator.value("total_filament_used"), 2),
            "electricity_total": round(self.coordinator.cost_total, 4),
            "last_print_cost": round(self.coordinator.value("last_print_cost"), 4),
            "last_idle_cost": round(self.coordinator.value("last_idle_cost"), 4),
        }


class TagLibrarySensor(BambuCostsSensor):
    """The filament tag library. State is the row count so it always changes."""

    # Deliberately no state_class: a row count is not a measurement, and the
    # class would have the recorder build long-term statistics nobody reads.
    _attr_icon = "mdi:tag-multiple"

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
            # The owning config entry: the card passes it back on every
            # service call, so several entries (a second printer, a test
            # entry) can be loaded without the calls becoming ambiguous.
            "entry_id": self.coordinator.entry.entry_id,
            "enabled_count": sum(1 for t in tags if not t.get("disabled")),
            "currency": self.coordinator.currency,
            "price_targets": self._price_targets(),
            # The palette's names, for the card's colour-name dropdown.
            "color_names": list(COLOR_NAME_OPTIONS),
        }

    def _price_targets(self) -> list[dict[str, str]]:
        """Every number a filament price can be pushed into, default first.

        Resolved from the registry rather than guessed, so the card does not
        have to reconstruct entity IDs from labels.
        """
        registry = er.async_get(self.hass)
        entry_id = self.coordinator.entry.entry_id

        wanted: list[tuple[str, str]] = [
            (CONF_DEFAULT_FILAMENT_PRICE, "Default price (backup)")
        ]
        wanted += [(slot.price_key, slot.label) for slot in self.coordinator.slots]

        targets: list[dict[str, str]] = []
        for key, label in wanted:
            entity_id = registry.async_get_entity_id("number", DOMAIN, f"{entry_id}_{key}")
            if entity_id:
                targets.append({"entity_id": entity_id, "label": label})
        return targets


class CurrentJobSensor(BambuCostsSensor):
    """The job on the printer now, as the row it would be logged as.

    State is ``printing`` or ``idle``. The ``row`` attribute is the live
    draft — the same one the manual forms open with — with the Printing-now
    card's edits applied; ``edited`` names the touched fields so the card can
    mark them. Its own tick keeps the measured parts (elapsed, energy,
    electricity so far) moving between state changes.
    """

    _attr_icon = "mdi:printer-3d-nozzle"

    def __init__(self, coordinator: BambuCostsCoordinator) -> None:
        super().__init__(coordinator, "current_job", "Current job")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_track_time_interval(
                self.hass, self._tick, timedelta(seconds=COST_TICK_SECONDS)
            )
        )

    @callback
    def _tick(self, _now: Any) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self) -> str:
        return "printing" if self.coordinator.print_running else "idle"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        draft = self.coordinator.draft_job()
        row = draft["row"]
        # The draft is failure-flavoured for the forms; this sensor is not.
        row["status"] = self.native_value
        return {
            "row": row,
            "edited": self.coordinator.overlay_fields(),
            "mins_planned": draft["mins_planned"],
            "cost_predicted": draft["cost_predicted"],
            "p_cost_predicted": draft["p_cost_predicted"],
            "currency": self.coordinator.currency,
            "entry_id": self.coordinator.entry.entry_id,
            # The slicer's render of the job, for the card to show — served
            # by the printer integration's image entity.
            "cover_entity": self.coordinator.entity_of(CONF_COVER_IMAGE) or "",
        }


class SpoolCountSensor(BambuCostsSensor):
    """How many physical spools the tag library describes.

    The tag library's state is its row count, but a paired spool is two rows,
    so the number the eye actually wants — how many spools — needs the
    pairing collapsed. Two instances: all spools, and only those still
    enabled. A spool with one side disabled and the other not counts as
    active — a spool is retired by disabling it whole.
    """

    # No state_class, for the same reason as the tag library.

    def __init__(
        self,
        coordinator: BambuCostsCoordinator,
        key: str,
        name: str,
        *,
        active_only: bool,
    ) -> None:
        super().__init__(coordinator, key, name)
        self._active_only = active_only
        self._attr_icon = "mdi:paper-roll" if active_only else "mdi:paper-roll-outline"

    @property
    def native_value(self) -> int:
        tags = self.coordinator.data.get("tags", [])
        if self._active_only:
            tags = [t for t in tags if not t.get("disabled")]
        return count_spools(tags)


class JobLogSensor(BambuCostsSensor):
    """Logged print jobs, newest last."""

    # No state_class, for the same reason as the tag library.
    _attr_icon = "mdi:history"

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
        return {
            "data": jobs,
            # Same contract as the tag library's: the card names this entry
            # on every save, draft and capture call.
            "entry_id": entry_id,
            "currency": self.coordinator.currency,
            # The jobs card shortens stored filament names against this list —
            # the configured one, or the shipped Bambu lineup when unset.
            "type_names": list(
                self.coordinator.options.get(CONF_FILAMENT_TYPES)
                or DEFAULT_FILAMENT_TYPES
            ),
        }
