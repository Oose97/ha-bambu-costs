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


# ── tags ─────────────────────────────────────────────────────────────────────
def test_tag_for_serial_matches_either_side():
    c = make()
    c.data = {"tags": [{"serial": "AAA", "serial_2": "BBB", "cost_per_kg": 13.22}]}
    assert c.tag_for_serial("bbb")["cost_per_kg"] == 13.22
    assert c.tag_for_serial("AAA")["cost_per_kg"] == 13.22
    assert c.tag_for_serial("CCC") is None
    assert c.tag_for_serial(None) is None
