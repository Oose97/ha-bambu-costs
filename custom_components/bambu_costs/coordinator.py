"""Runtime hub for one Bambu Print Costs config entry.

Holds the on-disk data, the user-settable cost values backing the ``number``
entities, and the per-slot filament maths that used to live in a Jinja macro.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.util import dt as dt_util
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import slugify

from .colors import UNKNOWN_COLOR, color_name
from .const import (
    DOMAIN,
    CONF_AUTO_LOG,
    CONF_CAMERA,
    CONF_COLOR_NAME_API,
    CONF_COVER_IMAGE,
    CONF_END_TIME,
    CONF_START_TIME,
    CONF_DEFAULT_FILAMENT_PRICE,
    CONF_CURRENCY,
    CONF_ELECTRICITY_PRICE,
    CONF_ELECTRICITY_PRICE_ENTITY,
    CONF_CURRENT_LAYER,
    CONF_ENERGY_SENSORS,
    CONF_FILAMENT_INVENTORY,
    CONF_LAYERS,
    CONF_LENGTH,
    CONF_NOZZLE_SIZE,
    CONF_NOZZLE_TYPE,
    CONF_POWER_SENSORS,
    CONF_PRINT_STATUS,
    CONF_PRINT_WEIGHT,
    CONF_SLOTS,
    CONF_TASK_NAME,
    DATA_DIR,
    DEFAULT_CURRENCY,
    DEFAULT_ELECTRICITY_PRICE,
    DEFAULT_FILAMENT_PRICE,
    EMPTY_TAG_UIDS,
    EXTERNAL_TOLERANCE_G,
    MAX_PLAUSIBLE_WATTS,
    NUMBER_DEFS,
    POWER_COST_TOLERANCE,
    SLOT_PRICE_PREFIX,
    SLOT_SEPARATOR,
)
from .storage import BambuCostsStore, as_float, distinct_filaments, normalise_colour

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
        # Whether job covers come from the camera instead of the slicer's
        # render. Owned by the "Use camera snapshot" switch, which restores it.
        self.use_camera_cover: bool = False
        # Log upkeep prints as electricity only — name "Maintenance", energy
        # and duration, no filament figures, no picture. Owned by the
        # "Maintenance mode" switch, which restores it.
        self.maintenance: bool = False
        self._tag_write_lock = asyncio.Lock()
        # Jobs have the same read-modify-write hazard: a card save landing
        # while a finished print is being appended must queue, not interleave.
        self._job_write_lock = asyncio.Lock()
        # Last breakdown that was computed from real per-slot data. Persisted by
        # the breakdown sensor, so a restart mid-print does not lose the split.
        self.last_good: dict[str, Any] | None = None
        # What each slot was printing from, remembered while the job runs so a
        # spool that runs out mid-print does not take its own identity and
        # price out of the job with it. Per print; persisted with the snapshot.
        self.slot_memory: dict[str, dict[str, Any]] = {}
        # The Printing-now card's edits to the current job — only the fields
        # the user touched. Loaded from disk at setup so a restart mid-print
        # keeps them; applied when the job is logged, cleared when a new one
        # starts. Everything untouched keeps following live data.
        self.overlay: dict[str, Any] = {}
        self._overlay_lock = asyncio.Lock()

        # Running cost total, restored by its sensor. _rate is the rate in
        # force since _rate_since, held so an interval can be charged at the
        # rate that actually applied to it.
        self.cost_total: float = 0.0
        self._rate: float = 0.0
        self._rate_since: datetime | None = None

        # Whether a print start was observed for the job now running. False
        # after a finish, and False at startup — a job already underway when
        # Home Assistant started has no valid integration window either.
        self._saw_print_start: bool = False
        # Wall-clock bounds of the current/last print, measured off the same
        # transitions the meters use, so the logged duration needs no sensor.
        self._print_started_at: datetime | None = None
        self._print_ended_at: datetime | None = None
        # Whether the current job has already been written to the log — the
        # integration logs on finish, and an automation calling log_job on the
        # same transition must not produce a second row.
        self._job_logged: bool = False
        # Whether the job that most recently *ended* had an observed start.
        # mark_print_end consumes _saw_print_start, and the job is logged from
        # an automation that runs after it — so the logging path needs its own
        # record of the provenance, or it would always read "start never seen".
        self._ended_had_start: bool = False
        # Task name captured when the markers were last set, so an ambiguous
        # start can be told apart from a genuinely new job.
        self._job_at_start: str = ""

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

    @property
    def currency(self) -> str:
        """Whatever the user calls their money. Only ever displayed."""
        return str(self.options.get(CONF_CURRENCY) or DEFAULT_CURRENCY).strip() or DEFAULT_CURRENCY

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
        """Find a tag-library row by RFID serial.

        A spool carries a tag on each side reporting different serials, so a
        row may name the other one. Either matches: whichever way round the
        spool goes in, it prices the same.
        """
        if not serial:
            return None
        wanted = str(serial).strip().lower()
        for tag in (self.data or {}).get("tags", []):
            if str(tag.get("serial", "")).strip().lower() == wanted:
                return tag
            if str(tag.get("serial_2", "")).strip().lower() == wanted:
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

    def sync_slot_prices(self) -> dict[str, float]:
        """Mirror what is actually loaded into each slot's price number.

        The number tracks the slot rather than being a setting: a slot holding
        a spool the tag library knows carries that price, and a slot that is
        empty — or holds a spool the library does not know — is set to 0. Zero
        is read by :meth:`slot_price` as "no price of its own", so costing falls
        back to the default.

        Three cases are deliberately skipped rather than zeroed, because none
        of them means "empty": a slot with no tray sensor configured, a tray
        whose own state is unavailable — typically the printer being switched
        off, which must not look like every spool was unloaded — and a loaded
        spool with no readable RFID tag. That last one is a generic spool:
        there is no tag to price it from, so its slot number is the user's to
        set by hand, and this runs on every tray update — zeroing there would
        wipe the manual price moments after it was typed in.
        """
        updated: dict[str, float] = {}
        for slot in self.slots:
            if not slot.entity:
                continue

            tray = self.tray_info(slot)
            if not tray.get("available"):
                continue

            serial = str(tray.get("tag_uid") or "").strip()
            if serial.lower() in EMPTY_TAG_UIDS and not tray.get("empty"):
                continue

            tag = self.tag_for_serial(serial)
            price = float(tag["cost_per_kg"]) if tag and tag.get("cost_per_kg") else 0.0
            if self.value(slot.price_key) != price:
                self.set_value(slot.price_key, price)
                updated[slot.label] = price
        return updated

    def loaded_spools(self) -> dict[str, str]:
        """Which tag is in which slot right now: serial -> slot label.

        Only trays with a readable tag appear — an empty slot, a generic
        spool, or a printer that is switched off contribute nothing, so the
        tags card's loaded chips never claim more than the AMS reported.
        """
        out: dict[str, str] = {}
        for slot in self.slots:
            tray = self.tray_info(slot)
            if not tray.get("available"):
                continue
            serial = str(tray.get("tag_uid") or "").strip()
            if serial and serial.lower() not in EMPTY_TAG_UIDS:
                out[serial] = slot.label
        return out

    def tray_info(self, slot: SlotDef) -> dict[str, Any]:
        """Colour, material and RFID serial for a slot, if a tray is mapped."""
        if not slot.entity:
            return {}
        state = self.hass.states.get(slot.entity)
        if state is None:
            return {"available": False}
        attrs = state.attributes
        return {
            "available": state.state.lower() not in _BAD_STATES,
            # True for a slot with nothing in it; False for a loaded spool,
            # tagged or not. A tray without the attribute reads as None, which
            # the price sync treats like a loaded spool — the safe direction,
            # since it never overwrites a price the user set by hand.
            "empty": attrs.get("empty"),
            "color": normalise_colour(attrs.get("color")) if attrs.get("color") else None,
            # `name` is the full product name ("Bambu PLA Basic"); `type` is
            # just the polymer ("PLA"). The tag library's filament column holds
            # the former, so both are carried.
            "name": attrs.get("name"),
            "material": attrs.get("type")
            or (state.state if state.state.lower() not in _BAD_STATES else None),
            "tag_uid": attrs.get("tag_uid"),
            # The cloud's per-spool id — the bridge between the tag the AMS
            # read and the printer's filament inventory.
            "tray_uuid": attrs.get("tray_uuid"),
        }

    # ── tag scanning ─────────────────────────────────────────────────────────
    async def async_add_scanned_tag(self, slot: SlotDef) -> dict[str, Any] | None:
        """Add a spool the AMS just read to the tag library, if it is new.

        The printer knows the material and colour of what was loaded but never
        its price, so a scanned row starts at 0 — which :meth:`slot_price` reads
        as "no price of its own" and falls back on. The row exists so the price
        can be filled in from the tags card instead of having to be typed from
        scratch after the spool is already in use.

        Returns the row that was added, or None when nothing was.
        """
        tray = self.tray_info(slot)
        serial = str(tray.get("tag_uid") or "").strip()
        if serial.lower() in EMPTY_TAG_UIDS:
            return None

        color_code = normalise_colour(tray.get("color") or "")
        tag = {
            "filament": tray.get("name") or tray.get("material") or "Unknown",
            "color_code": color_code,
            "color_name": await self._async_resolved_color_name(
                color_code, tray.get("material"), tray.get("name")
            ),
            "serial": serial,
            "cost_per_kg": 0.0,
            "disabled": False,
            "serial_2": "",
            "tray_uuid": str(tray.get("tray_uuid") or "").strip(),
        }

        # Reloading a whole AMS scans four spools at once, and add_tag_if_new is
        # a read-modify-write of the same file. Serialised here so concurrent
        # scans queue instead of overwriting each other.
        async with self._tag_write_lock:
            # A row seeded from the filament inventory knows this spool's id
            # but had no serial until now — claim it rather than adding a twin.
            claimed = await self.hass.async_add_executor_job(
                self.store.claim_seeded_row, serial, str(tray.get("tray_uuid") or "")
            )
            if claimed:
                added = False
            else:
                added = await self.hass.async_add_executor_job(
                    self.store.add_tag_if_new, tag
                )
        if claimed:
            _LOGGER.info(
                "Scanned tag %s claimed its inventory-seeded library row", serial
            )
            await self.async_request_refresh()
            return None
        if not added:
            return None
        await self.async_request_refresh()
        return tag

    # ── the cloud filament inventory ─────────────────────────────────────────
    def _inventory_spools(self) -> list[dict[str, Any]]:
        """The configured inventory sensor's spools, shaped for the store."""
        entity = self.entity_of(CONF_FILAMENT_INVENTORY)
        if not entity:
            return []
        state = self.hass.states.get(entity)
        if state is None or state.state.lower() in _BAD_STATES:
            return []
        spools = state.attributes.get("spools")
        if not isinstance(spools, list):
            return []

        out: list[dict[str, Any]] = []
        for spool in spools:
            if not isinstance(spool, dict):
                continue
            uuid = str(spool.get("rfid") or "").strip()
            if not uuid:
                continue
            name = str(spool.get("name") or "").strip()
            vendor = str(spool.get("vendor") or "").strip()
            # "Bambu Lab" + "PLA Basic" should read "Bambu PLA Basic", the way
            # the trays report it — not "Bambu Lab PLA Basic".
            product = (
                f"Bambu {name}"
                if vendor.lower().startswith("bambu")
                else f"{vendor} {name}".strip()
            )
            colour = normalise_colour(spool.get("color"))
            out.append(
                {
                    "tray_uuid": uuid,
                    "remaining_g": as_float(spool.get("remaining_g")),
                    # Brandless, to compare against library rows the same way
                    # the jobs card shortens them.
                    "match_name": name,
                    "color_code": colour,
                    "seed": {
                        "filament": product or "Unknown",
                        "color_code": colour,
                        "color_name": color_name(colour, spool.get("type"), product)
                        or UNKNOWN_COLOR,
                        "serial": "",
                        "cost_per_kg": 0.0,
                        "disabled": False,
                        "serial_2": "",
                        "tray_uuid": uuid,
                    },
                }
            )
        return out

    async def async_sync_inventory(self) -> dict[str, int] | None:
        """Fold the inventory sensor into the library, if one is configured."""
        spools = self._inventory_spools()
        if not spools:
            return None
        async with self._tag_write_lock:
            result = await self.hass.async_add_executor_job(
                self.store.sync_inventory, spools
            )
        if result.get("updated") or result.get("seeded"):
            await self.async_request_refresh()
        return result

    async def async_learn_tray_uuid(self, slot: SlotDef) -> dict[str, str] | None:
        """Learn the loaded spool's cloud id, and pair rows it betrays.

        Runs on every tag read, new spool or old: the store only ever fills
        blanks, so a quiet pass costs one file read and writes nothing.
        """
        tray = self.tray_info(slot)
        serial = str(tray.get("tag_uid") or "").strip()
        if serial.lower() in EMPTY_TAG_UIDS:
            return None
        async with self._tag_write_lock:
            changed = await self.hass.async_add_executor_job(
                self.store.learn_tray_uuid, serial, str(tray.get("tray_uuid") or "")
            )
        if changed:
            await self.async_request_refresh()
        return changed

    async def _async_resolved_color_name(
        self, color_code: str, material: str | None = None, product: str | None = None
    ) -> str:
        """Bambu's name for the colour, else the web's, else the placeholder.

        The material and product name narrow the palette to the right
        filament code — the same hex carries a different code per material
        AND per product line within it. The bundled palette only knows
        Bambu's own colours; a third-party spool's hex used to land as
        "Unknown Color", and when the option allows it, the color-names
        project's API gets one chance to do better.
        """
        name = color_name(color_code, material, product)
        if name != UNKNOWN_COLOR or not self.options.get(CONF_COLOR_NAME_API, True):
            return name
        return await self._async_lookup_color_name(color_code)

    async def _async_lookup_color_name(self, color_code: str) -> str:
        """Name an arbitrary hex via api.color.pizza (the color-names project).

        One tiny GET per newly scanned spool the palette does not know — a
        rare event. Any failure at all (offline instance, timeout, response
        shape change) falls back to the placeholder, exactly as if the
        lookup did not exist. It must never break or delay-block a scan.
        """
        from homeassistant.helpers.aiohttp_client import async_get_clientsession

        try:
            session = async_get_clientsession(self.hass)
            async with asyncio.timeout(10):
                response = await session.get(
                    "https://api.color.pizza/v1/",
                    params={"values": color_code.lstrip("#")},
                )
                data = await response.json()
            name = str(data["colors"][0]["name"]).strip()
            if name:
                return name
        except Exception:  # noqa: BLE001 — a naming nicety must never fail a scan
            _LOGGER.debug("Colour name lookup failed for %s", color_code, exc_info=True)
        return UNKNOWN_COLOR

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

    # ── running cost, integrated over time ───────────────────────────────────
    def cost_rate(self) -> float:
        """What the machine is costing right now, per hour.

        Power drawn now times the price now. Integrating this is what makes a
        variable tariff come out right — multiplying total kWh by the price at
        the end of a job charges the whole print at whatever the rate happened
        to be when it finished.
        """
        watts = 0.0
        for entity_id in self.options.get(CONF_POWER_SENSORS) or []:
            state = self.hass.states.get(entity_id)
            if state and state.state.lower() not in _BAD_STATES:
                watts += as_float(state.state)

        price, _source = self.electricity_price()
        return watts / 1000.0 * price

    @callback
    def accrue_cost(self, now: datetime | None = None) -> None:
        """Add what has been spent since the last tick to the running total.

        Left Riemann sum: the interval just elapsed is charged at the rate that
        was in force for it, then the rate is re-read. Because the amount comes
        from elapsed time rather than tick count, an irregular or missed tick
        costs freshness, never accuracy.
        """
        now = now or dt_util.utcnow()

        if self._rate_since is not None:
            hours = (now - self._rate_since).total_seconds() / 3600.0
            if hours > 0:
                self.cost_total += self._rate * hours

        self._rate = self.cost_rate()
        self._rate_since = now

    def spend_since(self, key: str) -> float:
        """Cost accumulated since a stored marker, never negative."""
        return max(0.0, self.cost_total - self.value(key))

    @property
    def print_running(self) -> bool:
        """Whether a print's start has been observed and not yet ended."""
        return self._saw_print_start

    @callback
    def _bank_through_now(self) -> float:
        """Bank all electricity accrued since the banked-through marker.

        ``cost_at_print_end`` doubles as the high-water mark of what has been
        banked: everything below it is already in ``total_cost``, everything
        between it and ``cost_total`` is not. Moving the marker and adding to
        the total happen together, here and nowhere else — so every accrued
        cent is banked exactly once, whether it was spent idling, printing, or
        in a stint that ended in an abort nothing ever logged.
        """
        amount = self.spend_since("cost_at_print_end")
        if amount > 0:
            self.set_value("total_cost", self.value("total_cost") + amount)
        self.set_value("cost_at_print_end", self.cost_total)
        return amount

    def _idle_window_spend(self) -> float:
        """Everything the current idle window has cost, restarts included.

        Measured off ``cost_at_idle_start``, which moves only when a print
        actually ends — a reconnect resync moves the banking marker but not
        this one, so a restart mid-idle no longer truncates the figure. The
        fallback covers an entry from before the marker existed: the banking
        marker gives the old (segment-only) behaviour for that one window.
        """
        base = self.value("cost_at_idle_start") or self.value("cost_at_print_end")
        return max(0.0, self.cost_total - base)

    @callback
    def mark_print_start(self, now: datetime | None = None, new_job: bool = True) -> float:
        """Close off the idle period and open the print one. Returns idle cost.

        A resume is not a new job: re-marking on the way back from a pause, or
        from a failure the printer recovered out of, would restart both meters
        part-way through and undercount everything already spent. So the
        markers are only moved for genuinely new work — a resume just brings
        the running total up to date.
        """
        self.accrue_cost(now)

        # Set for a resume as well as a new job: either way a print is now
        # known to be running, which is what makes its integration window and
        # its eventual end meaningful.
        self._saw_print_start = True
        if not new_job:
            return 0.0

        self._job_at_start = self._state(CONF_TASK_NAME) or ""
        # New work: whatever ended before belongs to a different job now.
        self._ended_had_start = False
        self._job_logged = False
        # ...including the card's edits to it, and what the slots were loaded
        # with. A resume keeps both — it is the same job continuing.
        self.slot_memory = {}
        if self.overlay:
            self.overlay = {}
            self.hass.async_add_executor_job(self.store.write_overlay, {})
        self._print_started_at = now or dt_util.utcnow()
        self._print_ended_at = None
        # The whole window since the last real print end — read before
        # banking, which moves the marker the fallback leans on.
        idle = self._idle_window_spend()
        self.set_value("last_idle_cost", idle)
        self._bank_through_now()
        self.set_value("cost_at_print_start", self.cost_total)
        # Snapshot the energy meters here rather than from an automation: the
        # print-start transition is already being watched, and the sensors are
        # already configured.
        self.set_value("energy_at_print_start", self.energy_now())
        return idle

    @callback
    def mark_print_end(self, now: datetime | None = None) -> float | None:
        """Close off the print period. Returns what its electricity cost.

        Returns ``None`` when nothing was running — a reconnect resync rather
        than a job ending — so the caller can tell "a print finished" apart
        from "the printer came back", and only auto-log the former.
        """
        self.accrue_cost(now)

        if not self._saw_print_start:
            # Nothing was running, so nothing ended — a printer reconnecting
            # re-reports the state it was already in, and `finish` is a state
            # it sits in indefinitely. Only the banked total is resynced, and
            # what accrued is banked rather than dropped. last_idle_cost is
            # left alone: the idle window is still open, and it is measured
            # off cost_at_idle_start when a print actually starts.
            idle = self._bank_through_now()
            # No job ended, so anything logged off this transition must not
            # claim an observed start it does not have.
            self._ended_had_start = False
            _LOGGER.debug(
                "Print-end resync with nothing running; banked %.4f %s of standby",
                idle,
                self.currency,
            )
            return None

        self._print_ended_at = now or dt_util.utcnow()
        spent = self.spend_since("cost_at_print_start")
        self.set_value("last_print_power_cost", spent)
        # The job's own energy, closed off here so a failed print logged from
        # the card later is not billed the standby that accrued in between.
        self.set_value("energy_at_print_end", self.energy_now())
        # The stint is banked here, not by log_job: an aborted print gets no
        # log call, and its electricity was just as real. log_job adds only
        # the filament, so nothing is counted twice.
        self._bank_through_now()
        # The idle window opens here, and only here — reconnect resyncs move
        # the banking marker but not this one, so a restart mid-idle cannot
        # truncate the next idle figure.
        self.set_value("cost_at_idle_start", self.cost_total)
        # Recorded before the running flag is cleared: the job is logged by an
        # automation that fires after this listener, and it needs to know the
        # ended job's start was observed even though nothing is running by then.
        self._ended_had_start = True
        self._saw_print_start = False
        return spent

    def resumes_marked_job(self) -> bool:
        """Whether the job now on the printer is the one the markers belong to.

        Only consulted for an ambiguous start — one arriving from a state that
        means contact was lost rather than one the printer reported. The same
        task name means the job was already underway and the markers still
        apply; a different one means a new job began unobserved.

        With no name to compare, this says resume. Keeping markers that turn
        out to be stale overcharges one print by the idle before it; discarding
        markers that were needed loses everything a running job had already
        spent, with nothing left to reconstruct it from.
        """
        current = self._state(CONF_TASK_NAME) or ""
        if not current or not self._job_at_start:
            return True
        return current == self._job_at_start

    def energy_now(self) -> float:
        """Summed kWh across every configured energy sensor."""
        total = 0.0
        for entity_id in self.options.get(CONF_ENERGY_SENSORS) or []:
            state = self.hass.states.get(entity_id)
            if state and state.state.lower() not in _BAD_STATES:
                total += as_float(state.state)
        return total

    # ── surviving a restart ──────────────────────────────────────────────────
    def _remember_breakdown(self, result: dict[str, Any]) -> None:
        """Keep the last breakdown that came from real per-slot data."""
        self.last_good = {
            "job": self._state(CONF_TASK_NAME) or "",
            "slots": [dict(row) for row in result["slots"]],
            "cost": result["cost"],
            "weight": result["weight"],
            "weight_total": result["weight_total"],
            "source": result["source"],
        }

    def _restored_breakdown(self, total_weight: float) -> dict[str, Any] | None:
        """Reuse the remembered split when the printer has stopped reporting it.

        After a Home Assistant restart the print weight sensor keeps its total
        but loses the per-slot attributes until the next print begins. Without
        this the whole job would fall through to the External branch and be
        repriced at the default — a plausible-looking but wrong number.

        Only reused when it is provably the same job: same name, same total.
        """
        snapshot = self.last_good
        if not snapshot:
            return None
        if snapshot.get("job", "") != (self._state(CONF_TASK_NAME) or ""):
            return None
        if abs(as_float(snapshot.get("weight_total")) - total_weight) > EXTERNAL_TOLERANCE_G:
            return None

        return {
            "slots": [dict(row) for row in snapshot["slots"]],
            "cost": snapshot["cost"],
            "weight": snapshot["weight"],
            "weight_total": snapshot["weight_total"],
            "source": snapshot["source"],
            # Prices are kept as they were rather than re-resolved: the tray
            # sensors lose their tag_uid in the same restart, so recomputing
            # would reintroduce the very fallback this exists to avoid.
            "restored": True,
        }

    @callback
    def forget_last_breakdown(self) -> None:
        """Drop the snapshot so a new job never inherits the previous split."""
        self.last_good = None

    # ── what is loaded in a slot ─────────────────────────────────────────────
    def _spool_in(self, slot: SlotDef, remember: bool = True) -> dict[str, Any]:
        """The spool a slot is printing from: identity, price, provenance.

        A spool that runs out mid-print is replaced, and the replacement is
        usually a bare one — the AMS reads no tag, so the slot goes from known
        to anonymous while the same job is still printing. Costing it live from
        that moment would price the whole job at the default, and log it with
        the new spool's blank name: the job would lose the very spool it was
        printed with, at the last minute.

        So a slot's resolved spool is remembered while the print runs, and an
        anonymous slot falls back to that memory. The memory is per print —
        cleared when a new job starts — and only ever fills a gap: a slot whose
        tag still reads, or one that never had a tag at all, is unaffected.
        """
        tray = self.tray_info(slot)
        tag = self.tag_for_serial(tray.get("tag_uid"))

        if tag is None and slot.key in self.slot_memory:
            spool = dict(self.slot_memory[slot.key])
            # Named apart from "tag" so the provenance stays honest: this is
            # what the slot held, not what it holds.
            spool["price_source"] = "remembered"
            return spool

        price, price_source = self.slot_price(slot, tag)
        spool = {
            "name": (tag or {}).get("color_name") or tray.get("material") or "",
            "material": tray.get("material") or "",
            # Full product name for the job log. The tag library's text wins —
            # it is the user's curated name ("SUNLU PETG HS Matte"), where the
            # tray just echoes whatever the tag encodes. A spool the library
            # does not match falls back to the printer's report.
            "filament": (tag or {}).get("filament") or tray.get("name") or "",
            "color": tray.get("color") or (tag or {}).get("color_code") or "",
            "price": price,
            "price_source": price_source,
        }

        # Only a tagged spool is worth remembering: it is the one whose
        # identity and price cannot be recovered once the tag is gone.
        if tag is not None and remember and self.print_running:
            self.slot_memory[slot.key] = dict(spool)
        return spool

    # ── filament breakdown ───────────────────────────────────────────────────
    def breakdown(self, remember: bool = True) -> dict[str, Any]:
        """Per-slot filament usage and cost for the current job.

        Nothing is rounded here — callers round at their own display point, so
        rows can never sum to a different figure than the total.

        ``remember=False`` makes this a pure read: display paths recompute on
        every state render, and a read should not be what updates the restart
        snapshot. The breakdown sensor and the action paths keep the default.
        """
        attrs = self._attrs(CONF_PRINT_WEIGHT)
        total_weight = as_float(self._state(CONF_PRINT_WEIGHT))

        rows: list[dict[str, Any]] = []
        for slot in self.slots:
            weight = as_float(attrs.get(slot.attribute))
            if weight <= 0:
                continue
            spool = self._spool_in(slot, remember=remember)
            rows.append(
                {
                    "id": slot.key,
                    "label": slot.label,
                    "attribute": slot.attribute,
                    **spool,
                    "weight": weight,
                    "cost": weight / 1000.0 * spool["price"],
                }
            )

        # No slot reported, but the printer still claims filament was used —
        # either a genuine external spool, or the per-slot attributes went away
        # under us. If we hold a snapshot of this same job, trust that instead.
        if not rows and total_weight > EXTERNAL_TOLERANCE_G:
            restored = self._restored_breakdown(total_weight)
            if restored is not None:
                return restored

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
                    "filament": "",
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

        result = {
            "slots": rows,
            "cost": sum(row["cost"] for row in rows),
            "weight": sum(row["weight"] for row in rows),
            "weight_total": total_weight,
            "source": source,
            "restored": False,
        }

        if remember and any(row["id"] != "external" for row in rows):
            self._remember_breakdown(result)
        return result

    # ── what the electricity for a job cost ──────────────────────────────────
    def power_cost_for_job(self, energy_kwh: float, minutes: float = 0.0) -> float:
        """Electricity cost for the job just finished.

        Integrating power is the better method when it works: a tariff that
        moved mid-print is charged as it actually moved, which multiplying
        total kWh by one price cannot do.

        It has one failure mode, and it is silent. Integrating a sensor that
        stops reporting yields nothing — a printer whose smart plug drops off
        the network for the length of a print integrates to about zero, and the
        result looks like a confident small number rather than missing data.
        An energy *counter* survives that: it keeps counting through the outage
        and the delta is still right once it reconnects.

        So the integral is used, but never blindly:

        * If no print start was observed, the window it integrated over does
          not correspond to this job at all. That happens when the printer
          finishes a job Home Assistant never saw begin — it went offline
          mid-job and came back reporting ``finish``.
        * If the counter says materially more energy was used than the integral
          charged for, the integral lost a stretch. It can only ever *under*
          count this way — a sensor that stops reporting cannot invent
          consumption — so the larger figure is the honest one.

        Either way the counter's figure wins and the shortfall is logged.

        The counter has its own failure mode, though, and it is the opposite
        one: a *discontinuity* rather than a gap. Repointing the energy sensors
        at different entities, a meter reset, or a counter rolling over all make
        the delta enormous rather than small. ``minutes`` guards against that —
        a delta implying a draw no domestic printer could produce is a
        discontinuity, not consumption, and the integral is kept instead.
        """
        price, price_source = self.electricity_price()
        metered = energy_kwh * price

        # Physically impossible readings are rejected before anything else, so
        # a discontinuity cannot be charged by either branch below.
        if minutes and minutes > 0:
            watts = energy_kwh * 1000.0 / (minutes / 60.0)
            if watts > MAX_PLAUSIBLE_WATTS:
                _LOGGER.error(
                    "Energy sensors report %.4f kWh over %.0f min — an average "
                    "of %.0f W, which no printer draws. Treating this as a "
                    "counter discontinuity (sensors repointed, meter reset or "
                    "rollover) rather than consumption. If you have just "
                    "changed which energy sensors are configured, set "
                    "energy_at_print_start to their current sum.",
                    energy_kwh, minutes, watts,
                )
                return self.spend_since("cost_at_print_start")

        if not self.options.get(CONF_POWER_SENSORS):
            _LOGGER.debug("Costing %s kWh at %s/kWh (%s)", energy_kwh, price, price_source)
            return metered

        integrated = self.spend_since("cost_at_print_start")

        # Either the job is still running with an observed start, or it just
        # ended and its end recorded that the start was observed. mark_print_end
        # clears the running flag before the logging automation fires, so the
        # flag alone would always say "never seen" here.
        if not (self._saw_print_start or self._ended_had_start):
            _LOGGER.warning(
                "This job's start was never seen — the printer was likely "
                "offline when it began — so the running total was not marked "
                "for it. Costing the %.4f kWh the energy sensors recorded at "
                "%s/kWh (%.4f %s) rather than the %.4f %s integrated over a "
                "window that belongs to an earlier job.",
                energy_kwh, price, metered, self.currency, integrated, self.currency,
            )
            return metered

        # A little slack so ordinary disagreement — the integral following a
        # tariff the flat price cannot, sensors sampling at different moments —
        # does not read as a lost stretch.
        if metered > integrated * (1.0 + POWER_COST_TOLERANCE):
            _LOGGER.warning(
                "Power integration captured %.4f %s but the energy sensors "
                "recorded %.4f kWh (%.4f %s at %s/kWh). A power sensor that "
                "stops reporting integrates to nothing, so this job most "
                "likely spans a gap; charging the metered figure.",
                integrated, self.currency, energy_kwh, metered, self.currency, price,
            )
            return metered

        return integrated

    # ── job logging ──────────────────────────────────────────────────────────
    @property
    def auto_log(self) -> bool:
        """Whether finished jobs are logged without an automation asking."""
        return bool(self.options.get(CONF_AUTO_LOG, True))

    def _ts(self, key: str) -> datetime | None:
        state = self._state(key)
        return dt_util.parse_datetime(state) if state else None

    def print_minutes(self) -> float:
        """How long the current or last print ran, in minutes.

        Measured off the same transitions the meters use, so no duration
        sensor is needed. A job whose start was never observed — a restart or
        an outage — falls back to the printer's own start/end time sensors,
        which re-report after a reconnect.
        """
        if self._print_started_at is not None:
            end = self._print_ended_at or dt_util.utcnow()
            return max(0.0, (end - self._print_started_at).total_seconds() / 60.0)

        start = self._ts(CONF_START_TIME)
        # While a print runs, the printer's end-time sensor is its ESTIMATE of
        # when the job will finish — measuring to it reports the whole planned
        # duration. What has actually elapsed is start → now; the estimate is
        # only trustworthy as an end once the job is over.
        if self._saw_print_start and start:
            return max(0.0, (dt_util.utcnow() - start).total_seconds() / 60.0)
        end = self._ts(CONF_END_TIME)
        if start and end and end > start:
            return (end - start).total_seconds() / 60.0
        return 0.0

    async def async_log_current_job(
        self,
        overrides: dict[str, Any] | None = None,
        capture_cover: bool = True,
        update_totals: bool = True,
        force: bool = False,
    ) -> dict[str, Any]:
        """Append the current job to the log — the one place a row is written.

        The integration logs on the finish transition and an automation may
        call ``log_job`` on the same transition, so the first write per job
        wins and the second is skipped. ``force`` is the deliberate override,
        for re-logging with corrected values.
        """
        if self._job_logged and not force:
            _LOGGER.debug("Job already logged; skipping duplicate log call")
            return {"logged": False, "reason": "already logged — pass force to re-log"}

        row = self.build_job_row(overrides or {})

        if capture_cover and not self.maintenance:
            stamp = str(row["timestamp"]).replace("-", "").replace(":", "").replace(" ", "-")
            row["cover"] = await self.async_capture_cover(stamp)

        await self.async_append_job(row)
        self._job_logged = True

        if update_totals:
            self.set_value("last_print_filament_cost", row["filament_cost"])
            self.set_value("last_print_power_cost", row["power_cost"])
            self.set_value("last_print_cost", row["total_cost"])
            self.set_value(
                "total_filament_used",
                self.value("total_filament_used") + row["weight_g"],
            )
            # Electricity is banked live by the coordinator whenever power
            # sensors are configured — the stint landed in the total at the
            # finish transition, aborted or not, so adding the row's power
            # here would count it twice. Without power sensors there is no
            # live banking, and the estimated power cost rides along instead.
            addition = row["filament_cost"]
            if not self.options.get(CONF_POWER_SENSORS):
                addition += row["power_cost"]
            self.set_value("total_cost", self.value("total_cost") + addition)

        return {"logged": True, "total_cost": row["total_cost"], "cover": row["cover"]}

    async def async_auto_log(self) -> None:
        """Log the job that just finished, guarded so a failure stays local."""
        try:
            result = await self.async_log_current_job()
        except Exception:  # noqa: BLE001 — must never take the listener down
            _LOGGER.exception("Auto-logging the finished job failed")
            return
        if result.get("logged"):
            _LOGGER.info("Logged finished job automatically (%s)", result.get("cover") or "no cover")

    def build_job_row(self, overrides: dict[str, Any]) -> dict[str, Any]:
        """Assemble one job-log row from live state plus any explicit values."""
        breakdown = self.breakdown()

        filament_cost = overrides.get("filament_cost")
        if filament_cost is None:
            filament_cost = breakdown["cost"]

        energy_kwh = overrides.get("energy_kwh")
        if energy_kwh is None:
            energy_kwh = max(0.0, self.energy_now() - self.value("energy_at_print_start"))

        # Read before the power cost: the duration is what makes an implausible
        # energy delta recognisable as a counter discontinuity. An explicit
        # override wins; otherwise the measured duration.
        if overrides.get("print_time_min") is not None:
            minutes = as_float(overrides.get("print_time_min"))
        else:
            minutes = self.print_minutes()

        power_cost = overrides.get("power_cost")
        if power_cost is None:
            power_cost = self.power_cost_for_job(energy_kwh, minutes)
        job_name = overrides.get("job") or self._state(CONF_TASK_NAME) or "unknown"

        row = {
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
            "trays": self._sensor_trays(breakdown),
            # The distinct types once each, however many slots fed the job —
            # "PLA Basic" for a single-material print, "PLA Basic, PETG HF"
            # for a multi-material one.
            "filament_type": overrides.get("filament_type")
            or distinct_filaments(breakdown["slots"]),
            "layers_done": as_float(overrides.get("layers_done")),
            "status": overrides.get("status") or "success",
        }
        # The card's mid-print edits land last — but an explicit service
        # override outranks them, so log_job stays the final word.
        row = self._overlaid_csv(row, set(overrides))

        # Maintenance mode outranks everything: an upkeep run bills its
        # electricity and nothing else. The filament figures the printer
        # reports for it are a plan for material not worth billing to any
        # spool, so they are blanked rather than logged.
        if self.maintenance:
            row.update(
                {
                    "job": "Maintenance",
                    "layers": 0.0,
                    "weight_g": 0.0,
                    "length_m": 0.0,
                    "nozzle_size": "",
                    "nozzle_type": "",
                    "filament_cost": 0.0,
                    "total_cost": round(as_float(row.get("power_cost")), 4),
                    "cover": "",
                    "trays": [],
                    "filament_type": "",
                }
            )
        return row

    def _overlaid_csv(self, row: dict[str, Any], explicit: set[str]) -> dict[str, Any]:
        """Apply the overlay to a CSV-shape row, minding explicit overrides."""
        if not self.overlay:
            return row
        mapping = {
            "job": "job",
            "layers": "layers",
            "weight": "weight_g",
            "length": "length_m",
            "nozzle": "nozzle_size",
            "nozzle_type": "nozzle_type",
            "types": "filament_type",
            "f_cost": "filament_cost",
        }
        out = dict(row)
        for overlay_key, csv_key in mapping.items():
            if overlay_key in self.overlay and csv_key not in explicit:
                out[csv_key] = self.overlay[overlay_key]
        tray_patches = self.overlay.get("trays")
        if isinstance(tray_patches, dict) and isinstance(out.get("trays"), list):
            trays = [dict(t) for t in out["trays"]]
            for index, fields in tray_patches.items():
                try:
                    position = int(index)
                except (TypeError, ValueError):
                    continue
                if 0 <= position < len(trays) and isinstance(fields, dict):
                    trays[position].update(fields)
            out["trays"] = trays
        # The total follows the edited filament; the power half is measured.
        if "total_cost" not in explicit:
            out["total_cost"] = round(
                as_float(out.get("filament_cost")) + as_float(out.get("power_cost")), 4
            )
        return out

    @staticmethod
    def _sensor_trays(breakdown: dict[str, Any]) -> list[dict[str, Any]]:
        """The breakdown's slots in the shape job rows carry them."""
        return [
            {
                "label": row["label"],
                "name": row["name"],
                # The full product name, brand included — the per-slot
                # detail is where the whole story belongs; the Material
                # column is the one that shortens.
                "type": row.get("filament") or row.get("material") or "",
                "color": row["color"],
                "weight": round(row["weight"], 3),
                "price": row["price"],
                "cost": round(row["cost"], 4),
            }
            for row in breakdown["slots"]
        ]

    # ── the current job's edits (the Printing-now card) ──────────────────────
    async def async_update_overlay(
        self, patch: dict[str, Any] | None, clear: bool = False
    ) -> dict[str, Any]:
        """Merge edits for the job on the printer, or drop them all.

        Only what the user touched is kept: every other field keeps following
        live data, and logging applies the overlay last. Tray patches merge
        per slot index, so editing one line never freezes its neighbours.
        """
        async with self._overlay_lock:
            if clear:
                self.overlay = {}
            elif patch:
                trays = patch.pop("trays", None)
                self.overlay.update(patch)
                if isinstance(trays, dict):
                    merged = dict(self.overlay.get("trays") or {})
                    for index, fields in trays.items():
                        if isinstance(fields, dict):
                            slot = dict(merged.get(str(index)) or {})
                            slot.update(fields)
                            merged[str(index)] = slot
                    self.overlay["trays"] = merged
            await self.hass.async_add_executor_job(
                self.store.write_overlay, self.overlay
            )
        self.async_update_listeners()
        return {"edited": self.overlay_fields()}

    def overlay_fields(self) -> list[str]:
        """The touched fields, tray edits as ``trays.<index>.<field>``."""
        fields: list[str] = []
        for key, value in self.overlay.items():
            if key == "trays" and isinstance(value, dict):
                for index, slot in value.items():
                    fields.extend(f"trays.{index}.{f}" for f in slot)
            else:
                fields.append(key)
        return sorted(fields)

    def _overlaid(self, row: dict[str, Any]) -> dict[str, Any]:
        """A sensor-shape row with the overlay's edits applied."""
        if not self.overlay:
            return row
        out = dict(row)
        for key in ("job", "layers", "weight", "length", "nozzle", "nozzle_type",
                    "types", "f_cost"):
            if key in self.overlay:
                out[key] = self.overlay[key]
        tray_patches = self.overlay.get("trays")
        if isinstance(tray_patches, dict) and isinstance(out.get("trays"), list):
            trays = [dict(t) for t in out["trays"]]
            for index, fields in tray_patches.items():
                try:
                    position = int(index)
                except (TypeError, ValueError):
                    continue
                if 0 <= position < len(trays) and isinstance(fields, dict):
                    trays[position].update(fields)
            out["trays"] = trays
        return out

    def draft_job(self) -> dict[str, Any]:
        """A pre-filled row for logging a print by hand, in the sensor's shape.

        Backs both of the jobs card's manual forms: a print that failed
        part-way, and a finished one the integration missed. Prefers the
        print on the printer now; with nothing running it describes the last
        one, whose sensors and markers all survive its end. Filament figures
        are the job's *plan* — the printer reports planned weights, not
        progress — so the failed form scales them by how many layers actually
        finished. Duration, energy and electricity are the measured reality
        of the stint and are not scaled.
        """
        breakdown = self.breakdown(remember=False)
        minutes = self.print_minutes()
        running = self.print_running

        if running:
            power_cost = self.spend_since("cost_at_print_start")
            energy_kwh = max(0.0, self.energy_now() - self.value("energy_at_print_start"))
        else:
            power_cost = self.value("last_print_power_cost")
            # The closing marker keeps post-failure standby out; entries from
            # before it existed fall back to the counter, standby included.
            energy_kwh = self.value("energy_at_print_end") - self.value(
                "energy_at_print_start"
            )
            if energy_kwh <= 0:
                energy_kwh = max(
                    0.0, self.energy_now() - self.value("energy_at_print_start")
                )

        # The planned duration, for the form to show next to the measured one
        # the way it shows layers done against layers total. Only a running
        # print knows it — the end-time sensor is the printer's estimated
        # finish then; once the job is over it is just the actual end.
        mins_planned = 0.0
        if running:
            start, end = self._ts(CONF_START_TIME), self._ts(CONF_END_TIME)
            if start and end and end > start:
                mins_planned = (end - start).total_seconds() / 60.0

        filament_cost = breakdown["cost"]
        row = {
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "job": self._state(CONF_TASK_NAME) or "",
            "time": f"{int(minutes) // 60}h {int(minutes) % 60}min" if minutes else "",
            "mins": round(minutes, 2),
            "layers": as_float(self._state(CONF_LAYERS)),
            "layers_done": as_float(self._state(CONF_CURRENT_LAYER)),
            "weight": round(breakdown["weight"], 3),
            "length": as_float(self._state(CONF_LENGTH)),
            "nozzle": self._state(CONF_NOZZLE_SIZE) or "",
            "nozzle_type": self._state(CONF_NOZZLE_TYPE) or "",
            "kwh": round(energy_kwh, 4),
            "f_cost": round(filament_cost, 4),
            "p_cost": round(power_cost, 4),
            "cost": round(filament_cost + power_cost, 4),
            "cover": "",
            "types": distinct_filaments(breakdown["slots"]),
            "trays": self._sensor_trays(breakdown),
            "status": "failed",
        }
        # The card's mid-print edits carry into everything drafted from this
        # job — the Printing-now view, and the failed/finished forms alike.
        row = self._overlaid(row)
        row["cost"] = round(as_float(row["f_cost"]) + as_float(row["p_cost"]), 4)

        # What the whole print is likely to cost: the filament is known up
        # front (the plan, or the user's edit of it); the electricity is
        # projected. Past 5% of the planned duration the print's own rate is
        # the best predictor — cost so far over fraction done. Earlier than
        # that the sample is mostly heat-up noise, so the last print's
        # measured rate stands in until this one has a track record.
        p_predicted = 0.0
        if running and mins_planned > 0:
            fraction = min(1.0, minutes / mins_planned)
            if fraction >= 0.05 and power_cost > 0:
                p_predicted = power_cost / fraction
            else:
                p_predicted = self._last_print_power_rate() * mins_planned
            # Never predict below what is already on the meter.
            p_predicted = max(p_predicted, power_cost)

        return {
            "running": running,
            "has_camera": bool(self.entity_of(CONF_CAMERA)),
            "mins_planned": round(mins_planned, 2),
            "p_cost_predicted": round(p_predicted, 4),
            "cost_predicted": round(as_float(row["f_cost"]) + p_predicted, 4)
            if p_predicted > 0
            else 0.0,
            "row": row,
        }

    def _last_print_power_rate(self) -> float:
        """The last logged print's electricity per minute, or 0 unknown."""
        jobs = (self.data or {}).get("jobs") or []
        if not jobs:
            return 0.0
        last = jobs[-1]
        minutes = as_float(last.get("mins"))
        power = as_float(last.get("p_cost"))
        if minutes <= 0 or power <= 0:
            return 0.0
        return power / minutes

    async def async_add_job(
        self,
        row: dict[str, Any],
        capture_cover: bool = True,
        update_totals: bool = False,
    ) -> dict[str, Any]:
        """Append one fully explicit row — the manual forms' save path.

        Unlike ``log_job`` this reads no live state and never touches the
        logged-once guard, so saving a failed print while the next job is
        already running cannot swallow that job's own auto-log. With no cover
        of its own the row gets the slicer's render — the camera shot is the
        form's deliberate capture button, never an automatic side effect.

        ``update_totals`` banks the row's filament (weight and cost) as the
        form shows them — for a failure that is the plan scaled by the layers
        that finished, not the full plan. Electricity is never added here:
        the coordinator banks it live, aborted stints included. The
        last-print markers are left alone — this row is history, not
        necessarily the latest print.
        """
        data = dict(row)
        data["ts"] = str(data.get("ts") or "").strip() or datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        csv_row = BambuCostsStore._job_to_csv(data)  # noqa: SLF001 — its canonical mapper

        if capture_cover and not csv_row["cover"]:
            stamp = (
                str(csv_row["timestamp"]).replace("-", "").replace(":", "").replace(" ", "-")
            )
            render = self.entity_of(CONF_COVER_IMAGE)
            if render:
                csv_row["cover"] = await self.async_capture_cover(stamp, sources=[render])

        await self.async_append_job(csv_row)

        if update_totals:
            weight = as_float(csv_row["weight_g"])
            filament_cost = as_float(csv_row["filament_cost"])
            self.set_value("total_cost", self.value("total_cost") + filament_cost)
            self.set_value(
                "total_filament_used", self.value("total_filament_used") + weight
            )

        return {
            "logged": True,
            "timestamp": csv_row["timestamp"],
            "cover": csv_row["cover"],
        }

    def _cover_sources(self) -> list[str]:
        """Entities to try for the job's picture, in order.

        With the camera switch on, the camera leads and the slicer's render
        stays as the fallback — a failed frame grab should degrade to the
        render, not to a job with no picture at all.
        """
        cover = self.entity_of(CONF_COVER_IMAGE)
        camera = self.entity_of(CONF_CAMERA)
        if self.use_camera_cover and camera:
            return [e for e in (camera, cover) if e]
        return [cover] if cover else []

    async def async_capture_cover(self, name: str, sources: list[str] | None = None) -> str:
        """Fetch and store the current job's picture. Returns the filename.

        A source may be an ``image`` (the slicer's render of the model) or a
        ``camera`` (a photo of what actually came off the plate — the job is
        logged the moment the printer reports finish, so the part is still on
        it). Each domain has its own fetch helper, so this dispatches; either
        way the bytes go through the same thumbnailing.

        ``sources`` overrides the configured preference — the failed-print
        form uses it to shoot the camera on demand, and to keep an automatic
        save to the render only.
        """
        for entity_id in sources if sources is not None else self._cover_sources():
            try:
                if entity_id.startswith("camera."):
                    from homeassistant.components.camera import async_get_image
                else:
                    from homeassistant.components.image import async_get_image

                image = await async_get_image(self.hass, entity_id, timeout=20)
            except Exception as err:  # noqa: BLE001 — a missing cover must not lose the job
                _LOGGER.warning("Could not fetch cover image from %s: %s", entity_id, err)
                continue
            return await self.hass.async_add_executor_job(
                self.store.save_cover, image.content, name
            )
        return ""

    # ── file access ──────────────────────────────────────────────────────────
    async def _async_update_data(self) -> dict[str, Any]:
        def _load() -> dict[str, Any]:
            self.store.ensure()
            return {"tags": self.store.read_tags(), "jobs": self.store.read_jobs()}

        return await self.hass.async_add_executor_job(_load)

    async def async_write_tags(self, tags: list[dict[str, Any]]) -> int:
        # Same lock as scanned adds: a card save landing while an AMS scan is
        # mid-write is a read-modify-write race on one file, and whichever
        # side loses is silently gone.
        async with self._tag_write_lock:
            written = await self.hass.async_add_executor_job(self.store.write_tags, tags)
        await self.async_request_refresh()
        return written

    async def async_set_tag_price(self, serial: str, price: float) -> int:
        async with self._tag_write_lock:
            changed = await self.hass.async_add_executor_job(
                self.store.set_tag_price, serial, price
            )
        if changed:
            await self.async_request_refresh()
        return changed

    async def async_append_job(self, row: dict[str, Any]) -> None:
        async with self._job_write_lock:
            await self.hass.async_add_executor_job(self.store.append_job, row)
        await self.async_request_refresh()

    async def async_write_jobs(self, rows: list[dict[str, Any]]) -> int:
        """Apply edited log rows. Raises LookupError when a row cannot be matched."""
        async with self._job_write_lock:
            written = await self.hass.async_add_executor_job(self.store.update_jobs, rows)
        await self.async_request_refresh()
        return written
