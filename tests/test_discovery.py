"""Device walk-up and slot-name parsing."""

import pytest

pytest.importorskip("homeassistant")

from custom_components.bambu_costs.discovery import (
    _parse_attribute,
    _root_device,
    _short_label,
    _slots_from_devices,
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


def test_idle_discovery_derives_slots_from_ams_device_names():
    """With no per-slot attributes to read, the AMS devices' own names —
    `…_AMS_{n}`, 1-based regular, 128-based HT — carry the numbering the
    attributes are built from, so the lines can be derived for review."""

    class Dev2:
        def __init__(self, id, name):
            self.id, self.name, self.via_device_id = id, name, None

    class Entry:
        def __init__(self, entity_id, device_id):
            self.entity_id, self.device_id = entity_id, device_id

    devices = Reg(
        Dev2("ams1", "P2S_SERIAL_AMS_1"),
        Dev2("ht", "P2S_SERIAL_AMS_128"),
        Dev2("ext", "P2S_SERIAL_ExternalSpool"),
    )
    trays = [
        Entry("sensor.p_ams_2_pro_tray_1", "ams1"),
        Entry("sensor.p_ams_2_pro_tray_2", "ams1"),
        Entry("sensor.p_ams_ht_tray_1", "ht"),
        Entry("sensor.p_external_spool", "ext"),
    ]
    lines, unpaired = _slots_from_devices(trays, devices)
    assert lines == [
        "AMS 1 Tray 1|A1|sensor.p_ams_2_pro_tray_1",
        "AMS 1 Tray 2|A2|sensor.p_ams_2_pro_tray_2",
        "AMS HT 1|HT1|sensor.p_ams_ht_tray_1",
    ]
    assert unpaired == ["sensor.p_external_spool"], \
        "the external spool has no per-slot attribute; it stays a remainder"


@pytest.mark.parametrize(
    ("attribute", "label"),
    [("AMS 1 Tray 1", "A1"), ("AMS 2 Tray 3", "A2-3"), ("AMS HT 1", "HT1"),
     ("External", "External")],
)
def test_short_labels(attribute, label):
    assert _short_label(attribute) == label
