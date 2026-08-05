"""Runtime hub for one Bambu Print Costs config entry.

Holds the on-disk data, the user-settable cost values backing the ``number``
entities, and the per-slot filament maths that used to live in a Jinja macro.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import slugify

from .const import (
    DOMAIN,
    CONF_COVER_IMAGE,
    CONF_DEFAULT_FILAMENT_PRICE,
    CONF_ELECTRICITY_PRICE,
    CONF_ELECTRICITY_PRICE_ENTITY,
    CONF_ENERGY_SENSORS,
    CONF_LAYERS,
    CONF_LENGTH,
    CONF_NOZZLE_SIZE,
    CONF_NOZZLE_TYPE,
    CONF_PRINT_STATUS,
    CONF_PRINT_WEIGHT,
    CONF_SLOTS,
    CONF_TASK_NAME,
    DATA_DIR,
    DEFAULT_ELECTRICITY_PRICE,
    DEFAULT_FILAMENT_PRICE,
    EXTERNAL_TOLERANCE_G,
    NUMBER_DEFS,
    SLOT_PRICE_PREFIX,
    SLOT_SEPARATOR,
)
from .storage import BambuCostsStore, as_float, normalise_colour

_LOGGER = logging.getLogger(__name__)

RELOAD_INTERVAL = timedelta(minutes=10)
_BAD_STATES = {"unknown", "unavailable", "none", ""}


@dataclass(frozen=True)
class SlotDef:
    """One filament source the printer reports a per-slot weight for."""

    attribute: str
    label: str
    entity: str | None = None

    @property
    def key(self) -> str:
        return slugify(self.attribute)

    @property
    def price_key(self) -> str:
        return f"{SLOT_PRICE_PREFIX}{self.key}"


def parse_slots(raw: list[str] | None) -> list[SlotDef]:
    """Turn the configured strings into slot definitions.

    Each entry is ``Attribute``, ``Attribute|Label`` or
    ``Attribute|Label|tray_entity_id``. The attribute is matched against
    ``print_weight``'s attributes verbatim — these names have changed across
    printer-integration releases before, so they are never guessed.

    The optional tray entity supplies the colour and material for the job log,
    and its ``tag_uid`` is used to price the slot from the tag library.
    """
    slots: list[SlotDef] = []
    for item in raw or []:
        parts = [p.strip() for p in str(item).split(SLOT_SEPARATOR)]
        if not parts or not parts[0]:
            continue
        slots.append(
            SlotDef(
                attribute=parts[0],
                label=parts[1] if len(parts) > 1 and parts[1] else parts[0],
                entity=parts[2] if len(parts) > 2 and parts[2] else None,
            )
        )
    return slots


class BambuCostsCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Owns files, cost values and derived maths for one entry."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{entry.title} data",
            update_interval=RELOAD_INTERVAL,
            # Passing the entry explicitly; inferring it is deprecated.
            config_entry=entry,
        )
        self.entry = entry
        self.store = BambuCostsStore(hass.config.path(DATA_DIR, entry.entry_id))
        self.slots = parse_slots(self.options.get(CONF_SLOTS))
        self.values: dict[str, float] = {}

    @property
    def device_info(self) -> DeviceInfo:
        """One device per entry, so every cost entity groups under it."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.entry.entry_id)},
            name=self.entry.title,
            manufacturer="Bambu Print Costs",
            entry_type=DeviceEntryType.SERVICE,
        )

    # ── config access ────────────────────────────────────────────────────────
    @property
    def options(self) -> dict[str, Any]:
        """Options win over the original setup data."""
        return {**self.entry.data, **self.entry.options}

    def entity_of(self, key: str) -> str | None:
        value = self.options.get(key)
        return value or None

    # ── cost values (backing the number entities) ────────────────────────────
    def default_value(self, key: str) -> float:
        for name, _label, _unit, _mn, _mx, _step, default in NUMBER_DEFS:
            if name == key:
                if default is not None:
                    return float(default)
                if key == CONF_ELECTRICITY_PRICE:
                    return float(
                        self.options.get(CONF_ELECTRICITY_PRICE, DEFAULT_ELECTRICITY_PRICE)
                    )
                if key == CONF_DEFAULT_FILAMENT_PRICE:
                    return float(
                        self.options.get(CONF_DEFAULT_FILAMENT_PRICE, DEFAULT_FILAMENT_PRICE)
                    )
        if key.startswith(SLOT_PRICE_PREFIX):
            return float(self.options.get(CONF_DEFAULT_FILAMENT_PRICE, DEFAULT_FILAMENT_PRICE))
        return 0.0

    def value(self, key: str) -> float:
        return self.values.get(key, self.default_value(key))

    def set_value(self, key: str, value: float) -> None:
        """Store a cost value and let every dependent entity recompute."""
        self.values[key] = float(value)
        self.async_update_listeners()

    def tag_for_serial(self, serial: str | None) -> dict[str, Any] | None:
        """Find a tag-library row by RFID serial."""
        if not serial:
            return None
        wanted = str(serial).strip().lower()
        for tag in (self.data or {}).get("tags", []):
            if str(tag.get("serial", "")).strip().lower() == wanted:
                return tag
        return None

    def slot_price(self, slot: SlotDef, tag: dict[str, Any] | None) -> tuple[float, str]:
        """Price for a slot, and where it came from.

        The spool actually loaded wins: if the tray reports an RFID serial that
        the tag library knows, that price is used. Otherwise the slot's own
        price number, then the default.
        """
        if tag and tag.get("cost_per_kg"):
            return float(tag["cost_per_kg"]), "tag"

        price = self.value(slot.price_key)
        if price > 0:
            return price, "slot"

        return self.value(CONF_DEFAULT_FILAMENT_PRICE), "default"

    def tray_info(self, slot: SlotDef) -> dict[str, Any]:
        """Colour, material and RFID serial for a slot, if a tray is mapped."""
        if not slot.entity:
            return {}
        state = self.hass.states.get(slot.entity)
        if state is None:
            return {}
        attrs = state.attributes
        return {
            "color": normalise_colour(attrs.get("color")) if attrs.get("color") else None,
            "material": attrs.get("type")
            or (state.state if state.state.lower() not in _BAD_STATES else None),
            "tag_uid": attrs.get("tag_uid"),
        }

    # ── state helpers ────────────────────────────────────────────────────────
    def _state(self, key: str) -> str | None:
        entity_id = self.entity_of(key)
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state.lower() in _BAD_STATES:
            return None
        return state.state

    def _attrs(self, key: str) -> dict[str, Any]:
        entity_id = self.entity_of(key)
        if not entity_id:
            return {}
        state = self.hass.states.get(entity_id)
        return dict(state.attributes) if state else {}

    def electricity_price(self) -> tuple[float, str]:
        """Price per kWh, and where it came from.

        A configured price sensor wins, so a variable tariff is followed
        instead of a figure that has to be kept up to date by hand. The number
        entity is the fallback for when no sensor is set or it is unavailable.
        """
        entity_id = self.entity_of(CONF_ELECTRICITY_PRICE_ENTITY)
        if entity_id:
            state = self.hass.states.get(entity_id)
            if state is not None and state.state.lower() not in _BAD_STATES:
                try:
                    # Spot tariffs can go negative, so no sign filtering here.
                    return float(str(state.state).strip().replace(",", ".")), "entity"
                except ValueError:
                    _LOGGER.warning(
                        "Electricity price sensor %s reports %r, which is not a "
                        "number — falling back to the price number entity",
                        entity_id,
                        state.state,
                    )
        return self.value(CONF_ELECTRICITY_PRICE), "number"

    def energy_now(self) -> float:
        """Summed kWh across every configured energy sensor."""
        total = 0.0
        for entity_id in self.options.get(CONF_ENERGY_SENSORS) or []:
            state = self.hass.states.get(entity_id)
            if state and state.state.lower() not in _BAD_STATES:
                total += as_float(state.state)
        return total

    # ── filament breakdown ───────────────────────────────────────────────────
    def breakdown(self) -> dict[str, Any]:
        """Per-slot filament usage and cost for the current job.

        Nothing is rounded here — callers round at their own display point, so
        rows can never sum to a different figure than the total.
        """
        attrs = self._attrs(CONF_PRINT_WEIGHT)
        total_weight = as_float(self._state(CONF_PRINT_WEIGHT))

        rows: list[dict[str, Any]] = []
        for slot in self.slots:
            weight = as_float(attrs.get(slot.attribute))
            if weight <= 0:
                continue
            tray = self.tray_info(slot)
            tag = self.tag_for_serial(tray.get("tag_uid"))
            price, price_source = self.slot_price(slot, tag)
            rows.append(
                {
                    "id": slot.key,
                    "label": slot.label,
                    "attribute": slot.attribute,
                    "name": (tag or {}).get("color_name") or tray.get("material") or "",
                    "material": tray.get("material") or "",
                    "color": tray.get("color") or (tag or {}).get("color_code") or "",
                    "weight": weight,
                    "price": price,
                    "price_source": price_source,
                    "cost": weight / 1000.0 * price,
                }
            )

        slot_weight = sum(row["weight"] for row in rows)
        default_price = self.value(CONF_DEFAULT_FILAMENT_PRICE)

        # Filament the printer counted but no configured slot claimed — an
        # external spool, or a slot whose attribute name drifted. Charging the
        # remainder keeps the rows summing to the reported total instead of
        # silently under-counting mixed jobs.
        remainder = total_weight - slot_weight
        if remainder > EXTERNAL_TOLERANCE_G:
            rows.append(
                {
                    "id": "external",
                    "label": "External",
                    "attribute": None,
                    "name": "",
                    "material": "",
                    "color": "",
                    "weight": remainder,
                    "price": default_price,
                    "price_source": "default",
                    "cost": remainder / 1000.0 * default_price,
                }
            )

        if not rows:
            source = "none"
        elif len(rows) == 1 and rows[0]["id"] == "external":
            source = "external"
        elif any(row["id"] == "external" for row in rows):
            source = "mixed"
        else:
            source = "slots"

        return {
            "slots": rows,
            "cost": sum(row["cost"] for row in rows),
            "weight": sum(row["weight"] for row in rows),
            "weight_total": total_weight,
            "source": source,
        }

    # ── job logging ──────────────────────────────────────────────────────────
    def build_job_row(self, overrides: dict[str, Any]) -> dict[str, Any]:
        """Assemble one job-log row from live state plus any explicit values."""
        breakdown = self.breakdown()

        filament_cost = overrides.get("filament_cost")
        if filament_cost is None:
            filament_cost = breakdown["cost"]

        energy_kwh = overrides.get("energy_kwh")
        if energy_kwh is None:
            energy_kwh = max(0.0, self.energy_now() - self.value("energy_at_print_start"))

        power_cost = overrides.get("power_cost")
        if power_cost is None:
            price, price_source = self.electricity_price()
            _LOGGER.debug("Costing %s kWh at %s EUR/kWh (%s)", energy_kwh, price, price_source)
            power_cost = energy_kwh * price

        minutes = as_float(overrides.get("print_time_min"))
        job_name = overrides.get("job") or self._state(CONF_TASK_NAME) or "unknown"

        return {
            "timestamp": overrides.get("timestamp")
            or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "job": job_name,
            "print_time": overrides.get("print_time")
            or (f"{int(minutes) // 60}h {int(minutes) % 60}min" if minutes else ""),
            "print_time_min": round(minutes, 2),
            "layers": overrides.get("layers") or as_float(self._state(CONF_LAYERS)),
            "weight_g": round(breakdown["weight"], 3),
            "length_m": overrides.get("length_m") or as_float(self._state(CONF_LENGTH)),
            "nozzle_size": overrides.get("nozzle_size") or self._state(CONF_NOZZLE_SIZE) or "",
            "nozzle_type": overrides.get("nozzle_type") or self._state(CONF_NOZZLE_TYPE) or "",
            "energy_kwh": round(energy_kwh, 4),
            "filament_cost": round(filament_cost, 4),
            "power_cost": round(power_cost, 4),
            "total_cost": round(filament_cost + power_cost, 4),
            "cover": "",
            "trays": [
                {
                    "label": row["label"],
                    "name": row["name"],
                    "color": row["color"],
                    "weight": round(row["weight"], 3),
                    "price": row["price"],
                    "cost": round(row["cost"], 4),
                }
                for row in breakdown["slots"]
            ],
        }

    async def async_capture_cover(self, name: str) -> str:
        """Fetch and store the current job's cover image. Returns the filename."""
        entity_id = self.entity_of(CONF_COVER_IMAGE)
        if not entity_id:
            return ""
        try:
            from homeassistant.components.image import async_get_image

            image = await async_get_image(self.hass, entity_id, timeout=20)
        except Exception as err:  # noqa: BLE001 — a missing cover must not lose the job
            _LOGGER.warning("Could not fetch cover image from %s: %s", entity_id, err)
            return ""
        return await self.hass.async_add_executor_job(
            self.store.save_cover, image.content, name
        )

    # ── file access ──────────────────────────────────────────────────────────
    async def _async_update_data(self) -> dict[str, Any]:
        def _load() -> dict[str, Any]:
            self.store.ensure()
            return {"tags": self.store.read_tags(), "jobs": self.store.read_jobs()}

        return await self.hass.async_add_executor_job(_load)

    async def async_write_tags(self, tags: list[dict[str, Any]]) -> int:
        written = await self.hass.async_add_executor_job(self.store.write_tags, tags)
        await self.async_request_refresh()
        return written

    async def async_set_tag_price(self, serial: str, price: float) -> int:
        changed = await self.hass.async_add_executor_job(
            self.store.set_tag_price, serial, price
        )
        if changed:
            await self.async_request_refresh()
        return changed

    async def async_append_job(self, row: dict[str, Any]) -> None:
        await self.hass.async_add_executor_job(self.store.append_job, row)
        await self.async_request_refresh()
