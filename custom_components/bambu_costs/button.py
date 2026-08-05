"""Manual actions that are deliberately not automatic."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import BambuCostsCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: BambuCostsCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([ChargeFilamentButton(coordinator)])


class ChargeFilamentButton(CoordinatorEntity[BambuCostsCoordinator], ButtonEntity):
    """Charge the current job's filament to the lifetime totals, by hand.

    For a print that failed part-way. Doing this automatically on a failure
    would be worse than not doing it: the printer reports the *planned* weight
    for the job, so a print that died on the first layer would be charged in
    full. Pressing this is a judgement call about how far it actually got, so
    it stays a judgement call.
    """

    _attr_has_entity_name = True
    _attr_name = "Charge filament to totals"
    _attr_icon = "mdi:cash-plus"

    def __init__(self, coordinator: BambuCostsCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_charge_filament"
        self._attr_device_info = coordinator.device_info
        self._last: dict[str, Any] = {}

    async def async_press(self) -> None:
        breakdown = self.coordinator.breakdown()
        cost = breakdown["cost"]
        weight = breakdown["weight"]

        if weight <= 0:
            self._last = {"error": "Nothing to charge — no filament reported"}
            self.async_write_ha_state()
            return

        self.coordinator.set_value(
            "total_cost", self.coordinator.value("total_cost") + cost
        )
        self.coordinator.set_value(
            "total_filament_used",
            self.coordinator.value("total_filament_used") + weight,
        )
        self.coordinator.set_value("last_print_filament_cost", cost)

        self._last = {
            "cost": round(cost, 4),
            "weight": round(weight, 3),
            "at": datetime.now().isoformat(timespec="seconds"),
            "slots": [
                {"label": row["label"], "weight": round(row["weight"], 3)}
                for row in breakdown["slots"]
            ],
        }
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """What the last press charged, so a mis-press is visible."""
        return {f"last_charged_{k}": v for k, v in self._last.items()}
