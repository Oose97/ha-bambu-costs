"""The cost accounting: banking, provenance, and the power-cost cross-check.

The coordinator is instantiated bare (``__new__``) and given only the state
these methods actually touch, so the accounting is tested as it ships without
needing a running Home Assistant.
"""

from types import SimpleNamespace

import pytest

homeassistant = pytest.importorskip("homeassistant")

from custom_components.bambu_costs.coordinator import BambuCostsCoordinator


def make(power_sensors=True, price=0.23):
    c = BambuCostsCoordinator.__new__(BambuCostsCoordinator)
    c.entry = SimpleNamespace(
        title="Test",
        data={"power_sensors": ["sensor.p"] if power_sensors else [],
              "energy_sensors": []},
        options={},
        entry_id="test",
    )
    c.values = {"total_cost": 100.0}
    c.cost_total = 0.0
    c._rate = 0.0
    c._rate_since = None
    c._saw_print_start = False
    c._ended_had_start = False
    c._job_at_start = ""
    c._job_logged = False
    c._print_started_at = None
    c._print_ended_at = None
    c.last_good = None
    # the pieces that would need hass, pinned per test instead
    c.async_update_listeners = lambda: None
    c.accrue_cost = lambda now=None: None
    c.energy_now = lambda: 0.0
    c.electricity_price = lambda: (price, "number")
    c._state = lambda key: "Job"
    return c


def log_job(c, filament, power):
    """Mirror the service's total update."""
    addition = filament
    if not c.options.get("power_sensors"):
        addition += power
    c.set_value("total_cost", c.value("total_cost") + addition)


# ── banking ──────────────────────────────────────────────────────────────────
def test_normal_job_banks_idle_stint_and_filament_once_each():
    c = make()
    c.cost_total = 0.30
    c.mark_print_start(new_job=True)
    c.cost_total = 0.55
    c.mark_print_end()
    log_job(c, filament=1.0, power=0.25)
    assert c.value("total_cost") == pytest.approx(101.55)
    assert c.value("last_print_power_cost") == pytest.approx(0.25)
    assert c.value("last_idle_cost") == pytest.approx(0.30)


def test_aborted_stint_reaches_the_total_without_a_log():
    c = make()
    c.cost_total = 0.10
    c.mark_print_start(new_job=True)
    c.cost_total = 0.1023
    c.mark_print_end()               # abort: nothing will log this
    c.cost_total = 0.15
    c.mark_print_start(new_job=True)
    assert c.value("total_cost") == pytest.approx(100.15)
    assert c.value("last_idle_cost") == pytest.approx(0.0477)


def test_jam_recovery_banks_power_exactly_once():
    c = make()
    c.mark_print_start(new_job=True)
    c.cost_total = 0.10
    c.mark_print_end()               # failed mid-print
    c.mark_print_start(new_job=False)  # recovered
    c.cost_total = 0.15
    c.mark_print_end()
    log_job(c, filament=0.50, power=0.15)
    assert c.value("total_cost") == pytest.approx(100.65)
    assert c.value("last_print_power_cost") == pytest.approx(0.15), \
        "the row reports the whole stint even though banking was split"


def test_reconnect_resync_banks_idle_and_records_no_print():
    c = make()
    c.cost_total = 0.30                      # standby accrued while away
    c.mark_print_end()                        # unavailable -> finish
    assert c.value("total_cost") == pytest.approx(100.30)
    assert c.value("last_print_power_cost") == 0.0
    assert c.value("cost_at_print_end") == pytest.approx(0.30)


def test_resync_flapping_banks_each_stretch_once():
    c = make()
    for step in (0.10, 0.20, 0.30):
        c.cost_total = step
        c._saw_print_start = False
        c.mark_print_end()
    assert c.value("total_cost") == pytest.approx(100.30)


# ── power cost for a logged job ──────────────────────────────────────────────
def test_integral_kept_after_the_listener_consumed_the_flag():
    c = make()
    c.mark_print_start(new_job=True)
    c.cost_total = 0.0465
    c.mark_print_end()               # clears the running flag before log_job
    assert c.power_cost_for_job(0.2141, 76.0) == pytest.approx(0.0465)


def test_counter_overrides_a_reporting_gap():
    c = make()
    c.mark_print_start(new_job=True)
    c.cost_total = 0.0165            # plug dropped off mid-print
    c.mark_print_end()
    assert c.power_cost_for_job(0.8372, 376.0) == pytest.approx(0.8372 * 0.23)


def test_phantom_finish_stays_metered():
    c = make()
    c.cost_total = 0.30
    c.mark_print_end()               # resync — no job ended
    assert c.power_cost_for_job(0.10, 60.0) == pytest.approx(0.10 * 0.23)


def test_discontinuity_guard_rejects_impossible_deltas():
    c = make()
    c.mark_print_start(new_job=True)
    c.cost_total = 0.0733
    c.mark_print_end()
    # repointed energy sensors: tens of kWh over a normal print
    assert c.power_cost_for_job(92.21, 376.0) == pytest.approx(0.0733)


def test_without_power_sensors_the_estimate_is_used():
    c = make(power_sensors=False)
    assert c.power_cost_for_job(0.8372, 376.0) == pytest.approx(0.8372 * 0.23)


# ── self-logging ─────────────────────────────────────────────────────────────
def test_resync_and_real_end_are_distinguishable():
    c = make()
    c.cost_total = 0.30
    assert c.mark_print_end() is None, "resync: nothing was running"
    c.mark_print_start(new_job=True)
    c.cost_total = 0.35
    assert c.mark_print_end() == pytest.approx(0.05), "a real end returns the stint"


def test_print_minutes_measured_and_fallback():
    import datetime as dt

    c = make()
    t0 = dt.datetime(2026, 8, 6, 12, 0, tzinfo=dt.UTC)
    c.mark_print_start(new_job=True, now=t0)
    c.mark_print_end(now=t0 + dt.timedelta(minutes=76))
    assert c.print_minutes() == pytest.approx(76.0)

    # start never observed: the printer's own clocks are the fallback
    c2 = make()
    c2._state = lambda key: {
        "start_time": "2026-08-06T15:53:42+00:00",
        "end_time": "2026-08-06T16:24:42+00:00",
    }.get(key, "Job")
    assert c2.print_minutes() == pytest.approx(31.0)

    c3 = make()
    c3._state = lambda key: None
    assert c3.print_minutes() == 0.0


def _run(coro):
    import asyncio

    return asyncio.new_event_loop().run_until_complete(coro)


def _loggable(c):
    """Stub the I/O around async_log_current_job so only the logic runs."""
    c.build_job_row = lambda overrides: {
        "timestamp": "2026-08-06 12:00:00", "filament_cost": 1.0,
        "power_cost": 0.25, "total_cost": 1.25, "weight_g": 40.0, "cover": "",
    }

    async def _noop_cover(name):
        return ""

    async def _noop_append(row):
        c.appended = getattr(c, "appended", 0) + 1

    c.async_capture_cover = _noop_cover
    c.async_append_job = _noop_append
    return c


def test_second_log_call_for_the_same_job_is_skipped():
    c = _loggable(make())
    c.mark_print_start(new_job=True)
    c.mark_print_end()

    first = _run(c.async_log_current_job())        # the integration, on finish
    second = _run(c.async_log_current_job())       # an automation, same finish
    assert first["logged"] is True
    assert second["logged"] is False
    assert c.appended == 1
    assert c.value("total_cost") == pytest.approx(101.0), "totals advanced once"

    forced = _run(c.async_log_current_job(force=True))
    assert forced["logged"] is True and c.appended == 2


def test_next_job_can_log_again():
    c = _loggable(make())
    c.mark_print_start(new_job=True)
    c.mark_print_end()
    _run(c.async_log_current_job())
    c.mark_print_start(new_job=True)               # new job resets the guard
    c.mark_print_end()
    assert _run(c.async_log_current_job())["logged"] is True
    assert c.appended == 2


def test_job_row_names_each_material_once():
    c = make()
    slots = [
        {"id": "a1", "label": "Tray 1", "name": "Green", "material": "PLA",
         "filament": "Bambu PLA Basic", "color": "#00AE42",
         "weight": 30.0, "price": 20.0, "cost": 0.6},
        {"id": "a2", "label": "Tray 2", "name": "Blue", "material": "PLA",
         "filament": "Bambu PLA Basic", "color": "#0A2989",
         "weight": 10.0, "price": 20.0, "cost": 0.2},
        {"id": "ht", "label": "HT", "name": "Black", "material": "PETG",
         "filament": "Bambu PETG HF", "color": "#000000",
         "weight": 5.0, "price": 25.0, "cost": 0.125},
    ]
    c.breakdown = lambda: {
        "slots": slots, "cost": 0.925, "weight": 45.0, "weight_total": 45.0,
        "source": "slots", "restored": False,
    }
    c.print_minutes = lambda: 76.0
    c.power_cost_for_job = lambda kwh, minutes: 0.05

    row = c.build_job_row({})
    assert row["filament_type"] == "PLA Basic, PETG HF"
    assert [t["type"] for t in row["trays"]] == ["PLA Basic", "PLA Basic", "PETG HF"]

    forced = c.build_job_row({"filament_type": "hand-typed"})
    assert forced["filament_type"] == "hand-typed", "the override wins"


def test_color_name_prefers_palette_then_api_then_placeholder():
    c = make()
    called = []

    async def fake_lookup(code):
        called.append(code)
        return "Jade Dream"

    c._async_lookup_color_name = fake_lookup

    # A Bambu colour never goes online.
    assert _run(c._async_resolved_color_name("#00AE42")) == "Bambu Green (10501)"
    assert called == []

    # An unknown hex asks the API when the option allows it (the default).
    assert _run(c._async_resolved_color_name("#123456")) == "Jade Dream"
    assert called == ["#123456"]

    # With the option off, the placeholder stands and nothing is called.
    c.entry.data["color_name_api"] = False
    assert _run(c._async_resolved_color_name("#123456")) == "Unknown Color"
    assert called == ["#123456"]


def test_generic_spool_scan_never_writes_a_library_row():
    """The tag library only ever holds tagged spools.

    A spool with no readable tag has no serial to match it by later — two
    generic spools are indistinguishable — and the printer does not even know
    what it is until the user says so. So loading one must not auto-add a row.
    """
    from custom_components.bambu_costs.coordinator import SlotDef

    c = make()
    slot = SlotDef(attribute="AMS 1 Tray 1", label="A1", entity="sensor.tray_1")
    for uid in ("", "0000000000000000", "unknown", None):
        c.tray_info = lambda s, uid=uid: {"available": True, "empty": False, "tag_uid": uid}
        assert _run(c.async_add_scanned_tag(slot)) is None


# ── slot price sync ──────────────────────────────────────────────────────────
def test_sync_leaves_a_generic_spools_manual_price_alone():
    """A loaded spool with no RFID tag is priced by hand, not zeroed.

    sync_slot_prices runs on every tray update, so if it zeroed a tagless
    slot, a manually entered price would be wiped moments after typing it.
    """
    from custom_components.bambu_costs.coordinator import SlotDef

    c = make()
    slot = SlotDef(attribute="AMS 1 Tray 1", label="A1", entity="sensor.tray_1")
    c.slots = [slot]
    c.data = {"tags": [{"serial": "AAA", "serial_2": "", "cost_per_kg": 13.22}]}
    c.set_value(slot.price_key, 18.0)

    trays = {}
    c.tray_info = lambda s: trays

    # Generic spool: loaded, but the printer read no tag.
    trays = {"available": True, "empty": False, "tag_uid": "0000000000000000"}
    assert c.sync_slot_prices() == {}
    assert c.value(slot.price_key) == 18.0

    # Same for a fork whose tray sensor has no empty attribute at all.
    trays = {"available": True, "empty": None, "tag_uid": ""}
    assert c.sync_slot_prices() == {}
    assert c.value(slot.price_key) == 18.0

    # Actually unloading the slot still clears it.
    trays = {"available": True, "empty": True, "tag_uid": ""}
    assert c.sync_slot_prices() == {"A1": 0.0}
    assert c.value(slot.price_key) == 0.0

    # And a known tag still takes over.
    trays = {"available": True, "empty": False, "tag_uid": "aaa"}
    assert c.sync_slot_prices() == {"A1": 13.22}


# ── tags ─────────────────────────────────────────────────────────────────────
def test_tag_for_serial_matches_either_side():
    c = make()
    c.data = {"tags": [{"serial": "AAA", "serial_2": "BBB", "cost_per_kg": 13.22}]}
    assert c.tag_for_serial("bbb")["cost_per_kg"] == 13.22
    assert c.tag_for_serial("AAA")["cost_per_kg"] == 13.22
    assert c.tag_for_serial("CCC") is None
    assert c.tag_for_serial(None) is None
