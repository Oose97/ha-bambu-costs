"""Work out the sensors and slots from a chosen printer device.

Entities are matched on their ``translation_key`` rather than on entity_id
suffixes, so a renamed entity is still found. Everything produced here is only
a pre-fill: the setup form shows what was found and the user can correct it,
because a wrong guess that is visible is recoverable and a silent one is not.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_COVER_IMAGE,
    CONF_LAYERS,
    CONF_LENGTH,
    CONF_NOZZLE_SIZE,
    CONF_NOZZLE_TYPE,
    CONF_PRINT_STATUS,
    CONF_PRINT_WEIGHT,
    CONF_SLOTS,
    CONF_TASK_NAME,
)

_LOGGER = logging.getLogger(__name__)

# Several candidates per role: the first that matches wins, so the list can
# carry both the current key and older spellings.
ROLE_KEYS: dict[str, tuple[str, ...]] = {
    CONF_PRINT_WEIGHT: ("print_weight",),
    CONF_PRINT_STATUS: ("print_status",),
    CONF_TASK_NAME: ("subtask_name", "task_name"),
    CONF_LAYERS: ("total_layers", "total_layer_count"),
    CONF_LENGTH: ("print_length",),
    CONF_NOZZLE_SIZE: ("nozzle_diameter", "nozzle_size"),
    CONF_NOZZLE_TYPE: ("nozzle_type",),
    CONF_COVER_IMAGE: ("cover_image",),
}

TRAY_KEY = "tray"


def _root_device(registry: dr.DeviceRegistry, device_id: str) -> str:
    """Follow ``via_device`` links up to the printer itself.

    ha-bambulab hangs every accessory — AMS units, the external spool, the
    hotend rack — off the printer via ``via_device``, and only the printer has
    no parent. Walking up means picking an AMS in the device selector
    discovers the printer it belongs to, instead of finding nothing.
    """
    seen: set[str] = set()
    device = registry.async_get(device_id)
    while device is not None and device.via_device_id:
        if device.id in seen:  # a cycle would be a registry bug; don't spin on it
            break
        seen.add(device.id)
        parent = registry.async_get(device.via_device_id)
        if parent is None:
            break
        device = parent
    return device.id if device else device_id


def _family(hass: HomeAssistant, device_id: str) -> set[str]:
    """The printer plus everything routed through it — AMS units, spools."""
    registry = dr.async_get(hass)
    ids = {device_id}
    for device in registry.devices.values():
        if device.via_device_id == device_id:
            ids.add(device.id)
    return ids


def _tokens(text: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", str(text).lower()) if t}


def discover(hass: HomeAssistant, device_id: str) -> dict[str, Any]:
    """Suggested config for a printer device, plus what could not be paired."""
    entities = er.async_get(hass)
    devices = dr.async_get(hass)
    # The user may have picked an AMS rather than the printer; same family.
    device_id = _root_device(devices, device_id)
    family = _family(hass, device_id)

    entries = [
        entry
        for did in family
        for entry in er.async_entries_for_device(entities, did, include_disabled_entities=False)
    ]

    found: dict[str, Any] = {}
    for role, keys in ROLE_KEYS.items():
        for key in keys:
            # Prefer an entity on the printer itself over one on a child device.
            matches = sorted(
                (e for e in entries if e.translation_key == key),
                key=lambda e: (e.device_id != device_id, e.entity_id),
            )
            if matches:
                found[role] = matches[0].entity_id
                break

    trays = sorted(
        (e for e in entries if e.translation_key == TRAY_KEY),
        key=lambda e: e.entity_id,
    )
    slots, unpaired = _pair_slots(hass, found.get(CONF_PRINT_WEIGHT), trays, devices)
    if slots:
        found[CONF_SLOTS] = slots

    _LOGGER.debug("Discovered %s from device %s", found, device_id)
    return {
        "config": found,
        "trays": [e.entity_id for e in trays],
        "unpaired_trays": unpaired,
    }


def _pair_slots(
    hass: HomeAssistant,
    print_weight: str | None,
    trays: list[er.RegistryEntry],
    devices: dr.DeviceRegistry,
) -> tuple[list[str], list[str]]:
    """Build slot lines from the live per-slot attributes.

    The attribute names are read off the print weight sensor rather than
    invented, since they are the only authority on what the printer calls each
    slot. A tray sensor is attached only when one candidate scores strictly
    better than the rest — an ambiguous pairing is left for the user, because
    quietly attaching the wrong tray would misprice a slot.
    """
    if not print_weight:
        return [], [e.entity_id for e in trays]

    state = hass.states.get(print_weight)
    if state is None:
        return [], [e.entity_id for e in trays]

    skip = {"unit_of_measurement", "device_class", "state_class", "friendly_name", "icon"}
    attributes = [a for a in state.attributes if a not in skip]

    # Structural, not bag-of-words: an AMS called "AMS 2 PRO" puts a 2 in its
    # device name, which a token count happily confuses with tray 2.
    candidates: list[tuple[str, int | None, set[str]]] = []
    for entry in trays:
        device = devices.async_get(entry.device_id) if entry.device_id else None
        m = re.search(r"tray[_ ]?(\d+)$", entry.entity_id, re.I)
        candidates.append(
            (entry.entity_id, int(m.group(1)) if m else None, _tokens(device.name if device else ""))
        )

    used: set[str] = set()
    paired: dict[str, str] = {}
    parsed = {a: _parse_attribute(a) for a in attributes}

    def claim(attribute: str, pool: list[tuple[str, int | None, set[str]]]) -> bool:
        free = [c for c in pool if c[0] not in used]
        if len(free) == 1:
            used.add(free[0][0])
            paired[attribute] = free[0][0]
            return True
        return False

    # Pass 1: the AMS designator names a device — "AMS HT 1" can only be the HT.
    for attribute, (unit, index) in parsed.items():
        if unit and not unit.isdigit():
            claim(attribute, [c for c in candidates if unit in c[2] and c[1] == index])

    # Pass 2: whatever is left, matched on tray number alone.
    for attribute, (_unit, index) in parsed.items():
        if attribute not in paired and index is not None:
            claim(attribute, [c for c in candidates if c[1] == index])

    lines = [
        f"{a}|{_short_label(a)}|{paired[a]}" if a in paired else f"{a}|{_short_label(a)}"
        for a in sorted(attributes)
    ]
    return lines, [eid for eid, _i, _t in candidates if eid not in used]


def _parse_attribute(attribute: str) -> tuple[str | None, int | None]:
    """'AMS 1 Tray 2' -> ('1', 2); 'AMS HT 1' -> ('ht', 1)."""
    m = re.match(r"^AMS\s+([A-Za-z0-9]+)\s+Tray\s+(\d+)$", attribute, re.I)
    if m:
        return m.group(1).lower(), int(m.group(2))
    m = re.match(r"^AMS\s+([A-Za-z]+)\s*(\d+)$", attribute, re.I)
    if m:
        return m.group(1).lower(), int(m.group(2))
    return None, None


def _short_label(attribute: str) -> str:
    """'AMS 1 Tray 1' -> 'A1', 'AMS HT 1' -> 'HT1', anything else unchanged."""
    m = re.match(r"^AMS\s+(\d+)\s+Tray\s+(\d+)$", attribute, re.I)
    if m:
        return f"A{m.group(2)}" if m.group(1) == "1" else f"A{m.group(1)}-{m.group(2)}"
    m = re.match(r"^AMS\s+([A-Z]+)\s*(\d+)$", attribute, re.I)
    if m:
        return f"{m.group(1).upper()}{m.group(2)}"
    return attribute
