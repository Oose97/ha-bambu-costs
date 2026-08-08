"""The CSV store: parsing, pairing, and the write paths."""

import pytest

from custom_components.bambu_costs.storage import (
    JOB_FIELDS,
    BambuCostsStore,
    as_float,
    count_spools,
    distinct_filaments,
    is_disabled,
    minimal_filament,
    normalise_colour,
)


def tag(serial, serial_2="", price=13.22, disabled=False):
    return {
        "filament": "Bambu PLA Basic",
        "color_code": "#00AE42",
        "color_name": "Bambu Green (10501)",
        "serial": serial,
        "cost_per_kg": price,
        "disabled": disabled,
        "serial_2": serial_2,
    }


@pytest.fixture
def store(tmp_path):
    st = BambuCostsStore(str(tmp_path))
    st.ensure()
    return st


def test_tags_round_trip(store):
    store.write_tags([tag("AAA", serial_2="BBB", disabled=True)])
    rows = store.read_tags()
    assert len(rows) == 1
    assert rows[0]["serial_2"] == "BBB"
    assert rows[0]["disabled"] is True
    assert rows[0]["cost_per_kg"] == 13.22


def test_either_serial_prices_the_spool(store):
    store.write_tags([tag("AAA", serial_2="BBB")])
    assert store.set_tag_price("bbb", 15.0) == 1
    assert store.set_tag_price("AAA", 16.0) == 1
    assert store.read_tags()[0]["cost_per_kg"] == 16.0


def test_scanning_the_far_side_of_a_pair_is_not_new(store):
    store.write_tags([tag("AAA", serial_2="BBB")])
    assert store.add_tag_if_new(tag("BBB")) is False
    assert store.add_tag_if_new(tag("CCC")) is True
    assert store.add_tag_if_new(tag("")) is False, "no serial, nothing to add"
    assert len(store.read_tags()) == 2


def test_rescan_is_a_no_op(store):
    assert store.add_tag_if_new(tag("AAA")) is True
    assert store.add_tag_if_new(tag("AAA")) is False
    assert len(store.read_tags()) == 1


def test_a_paired_spool_counts_once():
    tags = [tag("AAA", serial_2="BBB"), tag("BBB", serial_2="AAA"), tag("CCC")]
    assert count_spools(tags) == 2


def test_a_one_sided_pairing_still_counts_once():
    # A hand-edited file may carry the reference on only one of the rows.
    assert count_spools([tag("BBB"), tag("AAA", serial_2="BBB")]) == 1


def test_spool_serials_match_case_insensitively():
    assert count_spools([tag("aaa"), tag("BBB", serial_2="AAA")]) == 1


def test_a_row_with_no_serial_is_its_own_spool():
    assert count_spools([tag(""), tag("")]) == 2


def test_filtering_out_disabled_rows_keeps_the_half_enabled_pair():
    tags = [
        tag("AAA", serial_2="BBB"),
        tag("BBB", serial_2="AAA", disabled=True),
        tag("CCC", disabled=True),
    ]
    assert count_spools(tags) == 2
    assert count_spools([t for t in tags if not t["disabled"]]) == 1


def test_write_keeps_a_backup(store, tmp_path):
    store.write_tags([tag("AAA")])
    store.write_tags([tag("AAA"), tag("CCC")])
    assert (tmp_path / "tags.csv.bak").exists()


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("disabled", True), ("1", True), ("true", True), ("YES", True),
        ("", False), (None, False), ("nonsense", False), (True, True),
    ],
)
def test_disabled_column_is_lenient(value, expected):
    assert is_disabled(value) is expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [("13.22", 13.22), ("13,22", 13.22), ("1,300.5", 1300.5), ("", 0.0), ("x", 0.0)],
)
def test_as_float_accepts_both_separators(value, expected):
    assert as_float(value) == expected


def test_colour_normalised_to_rrggbb():
    assert normalise_colour("#00AE42FF") == "#00AE42"
    assert normalise_colour("00ae42") == "#00AE42"
    assert normalise_colour("nonsense") == "#808080"


# ── filament naming ──────────────────────────────────────────────────────────
def test_minimal_filament_drops_the_brand():
    assert minimal_filament("Bambu PLA Basic") == "PLA Basic"
    assert minimal_filament("  bambu  PETG HF ") == "PETG HF"
    assert minimal_filament("Sunlu PLA+") == "Sunlu PLA+", "other brands stay"
    assert minimal_filament("Bambulab PLA") == "Bambulab PLA", "only the word alone is a prefix"
    assert minimal_filament(None) == ""


def test_distinct_filaments_lists_each_material_once():
    slots = [
        {"filament": "Bambu PLA Basic"},
        {"filament": "Bambu PLA Basic"},
        {"filament": "Bambu PETG HF"},
        {"filament": "", "material": "TPU"},
        {"filament": "", "material": ""},  # untracked external: contributes nothing
    ]
    assert distinct_filaments(slots) == "PLA Basic, PETG HF, TPU"
    assert distinct_filaments([]) == ""


# ── the job log ──────────────────────────────────────────────────────────────
def job_row(ts, job="Benchy", types="PLA Basic"):
    return {
        "timestamp": ts,
        "job": job,
        "print_time": "1h 16min",
        "print_time_min": 76.0,
        "layers": 197.0,
        "weight_g": 42.5,
        "length_m": 14.2,
        "nozzle_size": "0.4",
        "nozzle_type": "stainless_steel",
        "energy_kwh": 0.214,
        "filament_cost": 0.85,
        "power_cost": 0.05,
        "total_cost": 0.9,
        "cover": "",
        "trays": [{"label": "Tray 1", "name": "Green", "type": types,
                   "color": "#00AE42", "weight": 42.5, "price": 20.0, "cost": 0.85}],
        "filament_type": types,
    }


def edit_for(row, **changes):
    """A card payload for one row: sensor shape plus the identity key."""
    edit = {
        "orig_ts": row["timestamp"], "ts": row["timestamp"], "job": row["job"],
        "time": row["print_time"], "mins": row["print_time_min"],
        "layers": row["layers"], "weight": row["weight_g"], "length": row["length_m"],
        "nozzle": row["nozzle_size"], "nozzle_type": row["nozzle_type"],
        "kwh": row["energy_kwh"], "f_cost": row["filament_cost"],
        "p_cost": row["power_cost"], "cost": row["total_cost"],
        "cover": row["cover"], "trays": row["trays"], "types": row["filament_type"],
    }
    edit.update(changes)
    return edit


def test_job_round_trip_carries_the_filament_type(store):
    store.append_job(job_row("2026-08-07 10:00:00", types="PLA Basic, PETG HF"))
    rows = store.read_jobs()
    assert rows[0]["types"] == "PLA Basic, PETG HF"
    assert rows[0]["trays"][0]["type"] == "PLA Basic, PETG HF"


def test_appending_to_an_old_header_upgrades_the_file(store, tmp_path):
    # A file from before filament_type existed: narrower header, one row.
    old_fields = JOB_FIELDS[:-1]
    with open(store.jobs_path, "w", encoding="utf-8", newline="") as handle:
        handle.write(",".join(old_fields) + "\n")
        handle.write("2026-08-01 09:00:00,Old job,1h 0min,60,100,10,3,0.4,steel,0.1,0.2,0.05,0.25,,[]\n")

    store.append_job(job_row("2026-08-07 10:00:00"))

    rows = store.read_jobs()
    assert len(rows) == 2, "the pre-upgrade row survives"
    assert rows[0]["job"] == "Old job" and rows[0]["types"] == ""
    assert rows[1]["types"] == "PLA Basic", "the new column is readable, not dropped"


def test_update_jobs_edits_in_place_and_spares_the_rest(store):
    for hour in ("10", "11", "12"):
        store.append_job(job_row(f"2026-08-07 {hour}:00:00", job=f"Job {hour}"))

    edit = edit_for(job_row("2026-08-07 11:00:00"), job="Renamed", cost=1.5)
    assert store.update_jobs([edit]) == 1

    rows = store.read_jobs()
    assert [r["job"] for r in rows] == ["Job 10", "Renamed", "Job 12"]
    assert rows[1]["cost"] == 1.5
    assert rows[0]["cost"] == 0.9 and rows[2]["cost"] == 0.9, "untouched rows keep their values"


def test_update_jobs_matches_by_original_timestamp(store):
    store.append_job(job_row("2026-08-07 10:00:00"))
    edit = edit_for(job_row("2026-08-07 10:00:00"), ts="2026-08-07 10:30:00")
    store.update_jobs([edit])
    assert store.read_jobs()[0]["ts"] == "2026-08-07 10:30:00"

    # A blanked timestamp falls back to the original instead of deleting the row.
    edit2 = edit_for(job_row("2026-08-07 10:30:00"), ts="")
    store.update_jobs([edit2])
    assert store.read_jobs()[0]["ts"] == "2026-08-07 10:30:00"


def test_update_jobs_refuses_a_row_the_file_no_longer_has(store, tmp_path):
    store.append_job(job_row("2026-08-07 10:00:00"))
    stranger = edit_for(job_row("2026-08-07 23:59:59"))
    with pytest.raises(LookupError):
        store.update_jobs([stranger])
    assert store.read_jobs()[0]["job"] == "Benchy", "a refused save writes nothing"
    assert not (tmp_path / "jobs.csv.bak").exists()


def test_update_jobs_pairs_duplicate_timestamps_in_order(store):
    store.append_job(job_row("2026-08-07 10:00:00", job="First"))
    store.append_job(job_row("2026-08-07 10:00:00", job="Second"))
    edits = [
        edit_for(job_row("2026-08-07 10:00:00"), job="First edited"),
        edit_for(job_row("2026-08-07 10:00:00"), job="Second edited"),
    ]
    store.update_jobs(edits)
    assert [r["job"] for r in store.read_jobs()] == ["First edited", "Second edited"]
