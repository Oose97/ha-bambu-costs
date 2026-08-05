"""Cost values as ``number`` entities.

These replace the ``input_number`` helpers the YAML setup needed. They are
plain, writable numbers: set them by hand in the UI, or from an automation with
``number.set_value``. Values survive restarts.
"""

from __future__ import annotations

from homeassistant.components.number import NumberMode, RestoreNumber
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_DEFAULT_FILAMENT_PRICE,
    CONF_ELECTRICITY_PRICE,
    DOMAIN,
    NUMBER_DEFS,
    SLOT_PRICE_PREFIX,
)
from .coordinator import BambuCostsCoordinator

# Settings the user configures, as opposed to running totals the integration
# maintains. Only affects where HA files them in the UI.
CONFIG_KEYS = {CONF_DEFAULT_FILAMENT_PRICE, CONF_ELECTRICITY_PRICE, "filter_change_due"}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the cost numbers, including one price per configured slot."""
    coordinator: BambuCostsCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[BambuCostsNumber] = [
        BambuCostsNumber(coordinator, key, name, unit, minimum, maximum, step)
        for key, name, unit, minimum, maximum, step, _default in NUMBER_DEFS
    ]

    entities.extend(
        BambuCostsNumber(
            coordinator,
            slot.price_key,
            f"{slot.label} filament price",
            "{currency}/kg",
            0,
            1000,
            0.01,
            config=True,
        )
        for slot in coordinator.slots
    )

    async_add_entities(entities)


class BambuCostsNumber(CoordinatorEntity[BambuCostsCoordinator], RestoreNumber):
    """A single writable cost value."""

    _attr_has_entity_name = True
    _attr_mode = NumberMode.BOX
    _attr_should_poll = False

    def __init__(
        self,
        coordinator: BambuCostsCoordinator,
        key: str,
        name: str,
        unit: str,
        minimum: float,
        maximum: float,
        step: float,
        config: bool | None = None,
    ) -> None:
        super().__init__(coordinator)
        self._key = key
        self._attr_name = name
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{key}"
        self._attr_native_unit_of_measurement = unit.format(currency=coordinator.currency)
        self._attr_native_min_value = minimum
        self._attr_native_max_value = maximum
        self._attr_native_step = step
        self._attr_device_info = coordinator.device_info

        is_config = config if config is not None else key in CONFIG_KEYS
        if is_config:
            self._attr_entity_category = EntityCategory.CONFIG

    async def async_added_to_hass(self) -> None:
        """Seed the value from the restored state, or the configured default."""
        await super().async_added_to_hass()

        restored = await self.async_get_last_number_data()
        if restored is not None and restored.native_value is not None:
            self.coordinator.values.setdefault(self._key, float(restored.native_value))
        else:
            self.coordinator.values.setdefault(
                self._key, self.coordinator.default_value(self._key)
            )
        self.async_write_ha_state()

    @property
    def native_value(self) -> float:
        return self.coordinator.value(self._key)

    async def async_set_native_value(self, value: float) -> None:
        self.coordinator.set_value(self._key, value)

    @property
    def extra_state_attributes(self) -> dict[str, str] | None:
        if not self._key.startswith(SLOT_PRICE_PREFIX):
            return None
        for slot in self.coordinator.slots:
            if slot.price_key == self._key:
                return {"print_weight_attribute": slot.attribute}
        return None
