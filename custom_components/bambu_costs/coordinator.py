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

from .colors import color_name
from .const import (
    DOMAIN,
    CONF_COVER_IMAGE,
    CONF_DEFAULT_FILAMENT_PRICE,
    CONF_CURRENCY,
    CONF_ELECTRICITY_PRICE,
    CONF_ELECTRICITY_PRICE_ENTITY,
    CONF_ENERGY_SENSORS,
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
        self._tag_write_lock = asyncio.Lock()
        # Last breakdown that was computed from real per-slot data. Persisted by
        # the breakdown sensor, so a restart mid-print does not lose the split.
        self.last_good: dict[str, Any] | None = None

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

        Two cases are deliberately skipped rather than zeroed, because neither
        means "empty": a slot with no tray sensor configured, and a tray whose
        own state is unavailable — typically the printer being switched off,
        which must not look like every spool was unloaded.
        """
        updated: dict[str, float] = {}
        for slot in self.slots:
            if not slot.entity:
                continue

            tray = self.tray_info(slot)
            if not tray.get("available"):
                continue

            tag = self.tag_for_serial(tray.get("tag_uid"))
            price = float(tag["cost_per_kg"]) if tag and tag.get("cost_per_kg") else 0.0
            if self.value(slot.price_key) != price:
                self.set_value(slot.price_key, price)
                updated[slot.label] = price
        return updated

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
            "color": normalise_colour(attrs.get("color")) if attrs.get("color") else None,
            # `name` is the full product name ("Bambu PLA Basic"); `type` is
            # just the polymer ("PLA"). The tag library's filament column holds
            # the former, so both are carried.
            "name": attrs.get("name"),
            "material": attrs.get("type")
            or (state.state if state.state.lower() not in _BAD_STATES else None),
            "tag_uid": attrs.get("tag_uid"),
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
            "color_name": color_name(color_code),
            "serial": serial,
            "cost_per_kg": 0.0,
            "disabled": False,
            "serial_2": "",
        }

        # Reloading a whole AMS scans four spools at once, and add_tag_if_new is
        # a read-modify-write of the same file. Serialised here so concurrent
        # scans queue instead of overwriting each other.
        async with self._tag_write_lock:
            added = await self.hass.async_add_executor_job(self.store.add_tag_if_new, tag)
        if not added:
            return None
        await self.async_request_refresh()
        return tag

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

    @callback
    def _bank_idle(self) -> float:
        """Close the open idle window, banking what standby cost. Returns it.

        The only place standby is ever banked. Anything that moves
        ``cost_at_print_end`` without coming through here silently discards
        every cent accrued since that marker last moved — which is exactly how
        a reconnect used to lose a night of idle.
        """
        idle = self.spend_since("cost_at_print_end")
        if idle <= 0:
            return 0.0
        self.set_value("last_idle_cost", idle)
        # Standby is real money — the printer idles at ~14 W — and nothing else
        # will ever bank it: log_job only adds what a print itself cost.
        self.set_value("total_cost", self.value("total_cost") + idle)
        return idle

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
        idle = self._bank_idle()
        self.set_value("cost_at_print_start", self.cost_total)
        # Snapshot the energy meters here rather than from an automation: the
        # print-start transition is already being watched, and the sensors are
        # already configured.
        self.set_value("energy_at_print_start", self.energy_now())
        return idle

    @callback
    def mark_print_end(self, now: datetime | None = None) -> float:
        """Close off the print period. Returns what its electricity cost."""
        self.accrue_cost(now)

        if not self._saw_print_start:
            # Nothing was running, so nothing ended — a printer reconnecting
            # re-reports the state it was already in, and `finish` is a state
            # it sits in indefinitely. Only the idle window is resynced, and
            # what accrued in it is banked rather than dropped. No print cost
            # is recorded, because no print ended.
            idle = self._bank_idle()
            self.set_value("cost_at_print_end", self.cost_total)
            # No job ended, so anything logged off this transition must not
            # claim an observed start it does not have.
            self._ended_had_start = False
            _LOGGER.debug(
                "Print-end resync with nothing running; banked %.4f %s of standby",
                idle,
                self.currency,
            )
            return 0.0

        spent = self.spend_since("cost_at_print_start")
        self.set_value("last_print_power_cost", spent)
        self.set_value("cost_at_print_end", self.cost_total)
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
        # energy delta recognisable as a counter discontinuity.
        minutes = as_float(overrides.get("print_time_min"))

        power_cost = overrides.get("power_cost")
        if power_cost is None:
            power_cost = self.power_cost_for_job(energy_kwh, minutes)
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
        await self.hass.async_add_executor_job(self.store.append_job, row)
        await self.async_request_refresh()
