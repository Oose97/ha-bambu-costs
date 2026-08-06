"""Device walk-up and slot-name parsing."""

import pytest

pytest.importorskip("homeassistant")

from custom_components.bambu_costs.discovery import (
    _parse_attribute,
    _root_device,
    _short_label,
)


class Dev:
    def __init__(self, id, via=None):
        self.id = id
        self.via_device_id = via


class Reg:
    def __init__(self, *devs):
        self._d = {d.id: d for d in devs}

    def async_get(self, id):
        return self._d.get(id)


def test_accessories_walk_up_to_the_printer():
    reg = Reg(Dev("printer"), Dev("ams", via="printer"), Dev("spool", via="printer"))
    assert _root_device(reg, "printer") == "printer"
    assert _root_device(reg, "ams") == "printer"
    assert _root_device(reg, "spool") == "printer"


def test_walk_survives_the_odd_registry():
    assert _root_device(Reg(Dev("ams", via="gone")), "ams") == "ams"
    assert _root_device(Reg(), "ghost") == "ghost"
    two = Reg(Dev("printer"), Dev("hub", via="printer"), Dev("ams", via="hub"))
    assert _root_device(two, "ams") == "printer"
    cycle = Reg(Dev("a", via="b"), Dev("b", via="a"))
    assert _root_device(cycle, "a") in ("a", "b"), "a cycle must terminate"


@pytest.mark.parametrize(
    ("attribute", "expected"),
    [
        ("AMS 1 Tray 2", ("1", 2)),
        ("AMS HT 1", ("ht", 1)),
        ("Something Else", (None, None)),
    ],
)
def test_attribute_parsing(attribute, expected):
    assert _parse_attribute(attribute) == expected


@pytest.mark.parametrize(
    ("attribute", "label"),
    [("AMS 1 Tray 1", "A1"), ("AMS 2 Tray 3", "A2-3"), ("AMS HT 1", "HT1"),
     ("External", "External")],
)
def test_short_labels(attribute, label):
    assert _short_label(attribute) == label
