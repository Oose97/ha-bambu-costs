"""The options round-trip: whatever the flow writes must survive it.

The options step rebuilds the entry from exactly ALL_KEYS and silently drops
anything else — so a key written to the flow's state but missing from the
tuple looks fine in the form and loses its value on the next save. That has
happened; this keeps it from happening again.
"""

import ast
import pathlib
from types import SimpleNamespace

import pytest

pytest.importorskip("homeassistant")

from custom_components.bambu_costs import config_flow
from custom_components.bambu_costs.config_flow import (
    ALL_KEYS,
    CONF_DEVICE,
    _device_from_entities,
)
from custom_components.bambu_costs.const import CONF_CAMERA, CONF_PRINT_STATUS


def test_device_and_camera_survive_the_round_trip():
    assert CONF_DEVICE in ALL_KEYS
    assert CONF_CAMERA in ALL_KEYS


def test_every_key_written_to_flow_state_is_persisted():
    source = pathlib.Path(config_flow.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    persisted = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "ALL_KEYS":
            persisted = {e.id for e in node.value.elts if isinstance(e, ast.Name)}
    assert persisted, "ALL_KEYS not found"

    written = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Subscript)
                and isinstance(node.value, ast.Attribute)
                and node.value.attr == "_data"
                and isinstance(node.slice, ast.Name)):
            written.add(node.slice.id)

    missing = written - persisted
    assert not missing, f"written to _data but dropped on save: {missing}"


def test_device_inferred_from_the_status_sensor(monkeypatch):
    """An entry from before the device id was stored still pre-fills the box."""
    registry = SimpleNamespace(
        async_get=lambda entity_id: SimpleNamespace(device_id="printer-1")
        if entity_id == "sensor.printer_status" else None
    )
    monkeypatch.setattr(config_flow.er, "async_get", lambda hass: registry)

    current = {CONF_PRINT_STATUS: "sensor.printer_status"}
    assert _device_from_entities(object(), current) == "printer-1"
    assert _device_from_entities(object(), {}) is None, "nothing configured, nothing guessed"
