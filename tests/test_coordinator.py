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
    c.slot_memory = {}
    c.overlay = {}
    # the pieces that would need hass, pinned per test instead
    c.hass = SimpleNamespace(async_add_executor_job=lambda fn, *a: fn(*a))
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


def test_idle_window_survives_a_reconnect_resync():
    """A restart mid-idle must not truncate the idle figure.

    The resync moves the banking marker — that is what stops double
    counting — but the idle window is measured off its own marker, set only
    when a print really ends, so the figure spans the whole window.
    """
    c = make()
    c.mark_print_start(new_job=True)
    c.cost_total = 0.10
    c.mark_print_end()                # idle window opens at 0.10
    c.cost_total = 0.20
    c._saw_print_start = False
    c.mark_print_end()                # reconnect resync mid-idle
    c.cost_total = 0.25
    c.mark_print_start(new_job=True)
    assert c.value("last_idle_cost") == pytest.approx(0.15), \
        "the whole window, not just the post-resync segment"
    assert c.value("total_cost") == pytest.approx(100.25), \
        "and still every cent banked exactly once"


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


def test_session_power_cost_follows_the_running_print():
    """The live session sensor: the integral while running, the last print's
    figure once it ends — never the idle accruing after the finish."""
    c = make()
    assert c.print_running is False
    c.mark_print_start(new_job=True)
    assert c.print_running is True
    c.cost_total = 0.04
    assert c.spend_since("cost_at_print_start") == pytest.approx(0.04)
    c.mark_print_end()
    assert c.print_running is False
    assert c.value("last_print_power_cost") == pytest.approx(0.04)
    c.cost_total = 0.09   # idle after the finish must not leak into the figure
    assert c.value("last_print_power_cost") == pytest.approx(0.04)


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


def test_a_running_prints_fallback_measures_elapsed_not_the_estimate():
    """Restart mid-print: the stopwatch is gone and the printer's end-time
    sensor is its ESTIMATED finish — the fallback must read start → now, or
    a failed print drafted mid-job reports the whole planned duration."""
    import datetime as dt

    c = make()
    c._saw_print_start = True
    start = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=30)
    estimate = dt.datetime.now(dt.UTC) + dt.timedelta(hours=3)
    c._state = lambda key: {
        "start_time": start.isoformat(),
        "end_time": estimate.isoformat(),
    }.get(key, "Job")
    assert c.print_minutes() == pytest.approx(30.0, abs=0.1)


def test_print_end_snapshots_the_energy_counter():
    c = make()
    c.energy_now = lambda: 5.2
    c.mark_print_start(new_job=True)
    c.energy_now = lambda: 5.9
    c.mark_print_end()
    assert c.value("energy_at_print_start") == pytest.approx(5.2)
    assert c.value("energy_at_print_end") == pytest.approx(5.9)


def _draftable(c):
    """Pin the live reads the failed-print draft leans on."""
    c.breakdown = lambda remember=True: {
        "slots": [{"id": "a1", "label": "Tray 1", "name": "Green", "material": "PLA",
                   "filament": "Bambu PLA Basic", "color": "#00AE42",
                   "weight": 40.0, "price": 20.0, "cost": 0.8}],
        "cost": 0.8, "weight": 40.0, "weight_total": 40.0,
        "source": "slots", "restored": False,
    }
    c.print_minutes = lambda: 90.0
    c._state = lambda key: {
        "task_name": "Benchy", "layers": "70", "current_layer": "30",
        "print_length": "14.2", "nozzle_size": "0.4", "nozzle_type": "hardened_steel",
    }.get(key)
    c.entity_of = lambda key: "camera.printer" if key == "camera_entity" else None
    return c


def test_draft_prefills_from_the_running_print():
    import datetime as dt

    c = _draftable(make())
    c._saw_print_start = True
    c.cost_total = 0.30
    c.values.update({"cost_at_print_start": 0.10, "energy_at_print_start": 4.5})
    c.energy_now = lambda: 5.0
    start = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=90)
    estimate = dt.datetime.now(dt.UTC) + dt.timedelta(minutes=120)
    base = c._state
    c._state = lambda key: {
        "start_time": start.isoformat(),
        "end_time": estimate.isoformat(),
    }.get(key) or base(key)

    d = c.draft_job()
    assert d["running"] is True and d["has_camera"] is True
    assert d["mins_planned"] == pytest.approx(210.0, abs=0.1), \
        "start to estimated finish — the plan the form shows the ran-time against"
    row = d["row"]
    assert row["status"] == "failed"
    assert row["layers"] == 70.0 and row["layers_done"] == 30.0
    assert row["kwh"] == pytest.approx(0.5)
    assert row["p_cost"] == pytest.approx(0.20), "the stint's own integral"
    assert row["f_cost"] == pytest.approx(0.8), "the plan — the card scales it"
    assert row["cost"] == pytest.approx(1.0)
    assert row["mins"] == pytest.approx(90.0) and row["time"] == "1h 30min"
    assert row["trays"][0]["type"] == "Bambu PLA Basic"
    assert row["types"] == "PLA Basic"


def test_draft_for_the_idle_printer_uses_the_closed_markers():
    c = _draftable(make())
    c.values.update({
        "last_print_power_cost": 0.25,
        "energy_at_print_start": 4.8,
        "energy_at_print_end": 5.2,
    })
    c.energy_now = lambda: 6.0  # standby kept counting after the failure

    d = c.draft_job()
    assert d["running"] is False
    assert d["row"]["p_cost"] == pytest.approx(0.25)
    assert d["row"]["kwh"] == pytest.approx(0.4), "post-failure standby stays out"

    # An entry from before the closing marker existed falls back to the
    # counter, standby included — a prefill beats a zero.
    c.values["energy_at_print_end"] = 0.0
    assert c.draft_job()["row"]["kwh"] == pytest.approx(1.2)


def test_overlay_edits_win_when_the_job_is_logged():
    c = _loggable_row(make())
    c.overlay = {
        "job": "Renamed mid-print",
        "f_cost": 0.5,
        "trays": {"0": {"price": 12.5, "cost": 0.5}},
    }
    row = c.build_job_row({})
    assert row["job"] == "Renamed mid-print"
    assert row["filament_cost"] == 0.5
    assert row["trays"][0]["price"] == 12.5
    assert row["total_cost"] == pytest.approx(0.5 + row["power_cost"]), \
        "the total follows the edited filament plus the measured power"


def test_explicit_overrides_outrank_the_overlay():
    c = _loggable_row(make())
    c.overlay = {"job": "From the card", "f_cost": 0.5}
    row = c.build_job_row({"job": "From the service", "filament_cost": 0.9})
    assert row["job"] == "From the service"
    assert row["filament_cost"] == 0.9


def test_a_new_job_clears_the_overlay_and_a_resume_keeps_it():
    c = make()
    written = []
    c.store = SimpleNamespace(write_overlay=written.append)
    c.overlay = {"job": "Edited"}
    c.mark_print_start(new_job=False)
    assert c.overlay == {"job": "Edited"}, "a resume is the same job continuing"
    c.mark_print_start(new_job=True)
    assert c.overlay == {}
    assert written == [{}], "the cleared overlay reaches the disk too"


def test_draft_carries_the_overlay_into_the_forms():
    c = _draftable(make())
    c.values.update({"last_print_power_cost": 0.25})
    c.overlay = {"job": "Edited name", "f_cost": 0.5}
    row = c.draft_job()["row"]
    assert row["job"] == "Edited name"
    assert row["f_cost"] == 0.5
    assert row["cost"] == pytest.approx(0.75)


def _planned(c, planned_minutes):
    import datetime as dt

    start = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=1)
    end = start + dt.timedelta(minutes=planned_minutes)
    base = c._state
    c._state = lambda key: {
        "start_time": start.isoformat(),
        "end_time": end.isoformat(),
    }.get(key) or base(key)
    return c


def test_prediction_extrapolates_from_the_prints_own_rate():
    c = _planned(_draftable(make()), 210)
    c._saw_print_start = True
    c.cost_total = 0.30
    c.values.update({"cost_at_print_start": 0.10, "energy_at_print_start": 4.5})
    c.energy_now = lambda: 5.0

    d = c.draft_job()  # 90 of 210 minutes, 0.20 spent
    assert d["p_cost_predicted"] == pytest.approx(0.20 / (90 / 210), abs=1e-3)
    assert d["cost_predicted"] == pytest.approx(0.8 + d["p_cost_predicted"], abs=1e-3)


def test_early_prediction_leans_on_the_last_prints_rate():
    c = _planned(_draftable(make()), 210)
    c._saw_print_start = True
    c.print_minutes = lambda: 5.0          # under 5% of the plan
    c.cost_total = 0.101
    c.values.update({"cost_at_print_start": 0.10, "energy_at_print_start": 4.5})
    c.energy_now = lambda: 5.0
    c.data = {"jobs": [{"mins": 76.0, "p_cost": 0.05}]}

    d = c.draft_job()
    assert d["p_cost_predicted"] == pytest.approx(0.05 / 76.0 * 210, abs=1e-3), \
        "the last print's measured rate, scaled to this plan"

    # With no history at all the floor is what the meter already shows.
    c.data = {"jobs": []}
    assert c.draft_job()["p_cost_predicted"] == pytest.approx(0.001)


def test_no_plan_means_no_prediction():
    c = _draftable(make())
    c._saw_print_start = True
    c.cost_total = 0.30
    c.values.update({"cost_at_print_start": 0.10})
    assert c.draft_job()["cost_predicted"] == 0.0


def test_update_overlay_merges_and_clears():
    import asyncio

    c = make()
    c._overlay_lock = asyncio.Lock()
    written = []

    async def _exec(fn, *args):
        return fn(*args)

    c.hass = SimpleNamespace(async_add_executor_job=_exec)
    c.store = SimpleNamespace(write_overlay=written.append)

    _run(c.async_update_overlay({"job": "A", "trays": {"0": {"price": 10.0}}}))
    _run(c.async_update_overlay({"trays": {"0": {"cost": 0.4}, "1": {"weight": 5.0}}}))
    assert c.overlay["job"] == "A"
    assert c.overlay["trays"]["0"] == {"price": 10.0, "cost": 0.4}, \
        "tray patches merge per slot instead of replacing each other"
    assert c.overlay["trays"]["1"] == {"weight": 5.0}

    out = _run(c.async_update_overlay(None, clear=True))
    assert c.overlay == {} and out == {"edited": []}
    assert written[-1] == {}


def _loggable_row(c):
    """Live reads pinned so build_job_row runs bare, like the logger uses it."""
    c.breakdown = lambda remember=True: {
        "slots": [{"id": "a1", "label": "Tray 1", "name": "Green", "material": "PLA",
                   "filament": "Bambu PLA Basic", "color": "#00AE42",
                   "weight": 40.0, "price": 20.0, "cost": 0.8}],
        "cost": 0.8, "weight": 40.0, "weight_total": 40.0,
        "source": "slots", "restored": False,
    }
    c.print_minutes = lambda: 76.0
    c.power_cost_for_job = lambda kwh, minutes: 0.05
    return c


def test_add_job_appends_verbatim_and_leaves_the_guard_alone():
    c = make()
    captured = []

    async def _append(row):
        captured.append(row)

    c.async_append_job = _append
    c.entity_of = lambda key: None

    out = _run(c.async_add_job(
        {"ts": "2026-08-07 14:00:00", "job": "Died at 30", "weight": 12.5,
         "f_cost": 0.25, "p_cost": 0.05, "cost": 0.3, "layers": 70,
         "layers_done": 30, "status": "failed", "trays": []},
        capture_cover=True, update_totals=True,
    ))

    assert out["logged"] is True
    assert captured[0]["status"] == "failed"
    assert captured[0]["layers_done"] == 30.0
    assert c._job_logged is False, "the running job's own auto-log must survive"
    assert c.value("total_cost") == pytest.approx(100.25), \
        "filament only — electricity is banked live, aborts included"
    assert c.value("total_filament_used") == pytest.approx(12.5)


def test_add_job_stamps_a_blank_timestamp():
    c = make()
    captured = []

    async def _append(row):
        captured.append(row)

    c.async_append_job = _append
    c.entity_of = lambda key: None

    _run(c.async_add_job({"job": "No ts"}, capture_cover=False))
    assert captured[0]["timestamp"], "a blank timestamp would make the row invisible"


def test_breakdown_prefers_the_tag_librarys_filament_name():
    """The library's curated name beats the printer's echo of the tag.

    A clone-tagged SUNLU spool reads as "Bambu PETG HF" on the tray, but the
    user has named it properly in the library; the log should carry their
    name. A spool the library does not know keeps the printer's report.
    """
    from custom_components.bambu_costs.coordinator import SlotDef

    c = make()
    slot = SlotDef(attribute="AMS 1 Tray 1", label="A1", entity="sensor.tray_1")
    c.slots = [slot]
    c._attrs = lambda key: {"AMS 1 Tray 1": 10.0}
    c.data = {"tags": [{"serial": "AAA", "serial_2": "",
                        "filament": "SUNLU PETG HS Matte",
                        "color_name": "White", "cost_per_kg": 9.35}]}
    tray = {"available": True, "name": "Bambu PETG HF", "material": "PETG",
            "tag_uid": "AAA", "color": "#FFFFFF"}
    c.tray_info = lambda s: tray

    assert c.breakdown(remember=False)["slots"][0]["filament"] == "SUNLU PETG HS Matte"

    tray = {"available": True, "name": "Bambu PETG HF", "material": "PETG",
            "tag_uid": "", "color": "#FFFFFF"}
    assert c.breakdown(remember=False)["slots"][0]["filament"] == "Bambu PETG HF"


def _one_tagged_slot(c):
    """One slot, one library spool, the tray under the test's control."""
    from custom_components.bambu_costs.coordinator import SlotDef

    slot = SlotDef(attribute="AMS 1 Tray 1", label="A1", entity="sensor.tray_1")
    c.slots = [slot]
    c._attrs = lambda key: {"AMS 1 Tray 1": 40.0}
    c.data = {"tags": [{"serial": "AAA", "serial_2": "", "filament": "Bambu PLA Basic",
                        "color_name": "Jade White (10100)", "color_code": "#FFFFFF",
                        "cost_per_kg": 13.22}]}
    c.tray_info = lambda s: c._tray
    c._tray = {"available": True, "empty": False, "name": "Bambu PLA Basic",
               "material": "PLA", "tag_uid": "AAA", "color": "#FFFFFF"}
    return c


def test_a_spool_running_out_mid_print_keeps_what_it_was_printed_with():
    """The AMS reads no tag on the replacement, so the slot goes anonymous
    while the same job prints. It must keep costing what it started with."""
    c = _one_tagged_slot(make())
    c.mark_print_start(new_job=True)

    row = c.breakdown()["slots"][0]
    assert row["price"] == 13.22 and row["price_source"] == "tag"

    # Ran out; the user drops in a bare spool the AMS cannot read.
    c._tray = {"available": True, "empty": False, "name": None,
               "material": None, "tag_uid": "0000000000000000", "color": None}

    row = c.breakdown()["slots"][0]
    assert row["price"] == 13.22, "still the spool the job was printed with"
    assert row["price_source"] == "remembered"
    assert row["filament"] == "Bambu PLA Basic"
    assert row["name"] == "Jade White (10100)"
    assert row["color"] == "#FFFFFF"


def test_the_memory_still_applies_when_the_job_is_logged():
    """A spool that runs out at the very end: the row is built after the
    print-end transition, and must still carry the real spool."""
    c = _one_tagged_slot(make())
    c.mark_print_start(new_job=True)
    c.breakdown()
    c.mark_print_end()
    c._tray = {"available": True, "empty": True, "name": None,
               "material": None, "tag_uid": None, "color": None}

    c.print_minutes = lambda: 60.0
    c.power_cost_for_job = lambda kwh, minutes: 0.05
    row = c.build_job_row({})
    assert row["trays"][0]["price"] == 13.22
    assert row["trays"][0]["type"] == "Bambu PLA Basic"
    assert row["filament_type"] == "PLA Basic"
    assert row["filament_cost"] == pytest.approx(40.0 / 1000 * 13.22, abs=1e-4)


def test_the_next_job_starts_from_what_is_actually_loaded():
    c = _one_tagged_slot(make())
    c.mark_print_start(new_job=True)
    c.breakdown()
    c.mark_print_end()

    c._tray = {"available": True, "empty": False, "name": None,
               "material": None, "tag_uid": "0000000000000000", "color": None}
    c.mark_print_start(new_job=True)

    row = c.breakdown()["slots"][0]
    assert row["price_source"] != "remembered", "a new job inherits nothing"
    assert row["filament"] == ""


def test_a_resume_keeps_the_memory():
    c = _one_tagged_slot(make())
    c.mark_print_start(new_job=True)
    c.breakdown()
    c._tray = {"available": True, "empty": False, "name": None,
               "material": None, "tag_uid": "0000000000000000", "color": None}
    c.mark_print_start(new_job=False)  # a pause, or a jam recovered
    assert c.breakdown()["slots"][0]["price"] == 13.22


def test_a_slot_that_never_had_a_tag_is_untouched():
    c = _one_tagged_slot(make())
    c._tray = {"available": True, "empty": False, "name": None,
               "material": None, "tag_uid": "0000000000000000", "color": None}
    c.values[c.slots[0].price_key] = 18.0
    c.mark_print_start(new_job=True)

    row = c.breakdown()["slots"][0]
    assert row["price"] == 18.0 and row["price_source"] == "slot", \
        "a generic spool still prices from its slot number"


def test_nothing_is_remembered_between_prints():
    """Off the clock the printer is not printing this job — a tag read while
    idle must not become the next job's fallback."""
    c = _one_tagged_slot(make())
    c.breakdown()  # idle: no print start observed
    assert c.slot_memory == {}


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
    # The per-tray detail keeps the full product name, brand included; only
    # the aggregated column and its display are shortened.
    assert [t["type"] for t in row["trays"]] == [
        "Bambu PLA Basic", "Bambu PLA Basic", "Bambu PETG HF"]

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
