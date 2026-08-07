"""The CSV store: parsing, pairing, and the write paths."""

import pytest

from custom_components.bambu_costs.storage import (
    BambuCostsStore,
    as_float,
    is_disabled,
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
