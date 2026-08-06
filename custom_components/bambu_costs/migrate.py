"""Import CSVs written by the pre-integration YAML/shell setup.

Both legacy files are headerless. Tags are close enough to the new shape to be
read directly, but the job log is not: it carried a derived ``eur_per_100g``
column that has been dropped, and packed the per-tray detail into a delimited
string instead of JSON. Everything here runs in the executor.
"""

from __future__ import annotations

import csv
import logging
import os
import shutil
from typing import Any

from .storage import BambuCostsStore, as_float, is_disabled, normalise_colour

_LOGGER = logging.getLogger(__name__)

# timestamp, job, print_time, print_time_min, layers, weight_g, length_m,
# nozzle_size, nozzle_type, energy_kwh, filament_cost, power_cost, total_cost,
# eur_per_100g, cover, trays
LEGACY_JOB_COLUMNS = 16
_EUR_PER_100G_INDEX = 13


def _rows(path: str) -> list[list[str]]:
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        return [row for row in csv.reader(handle) if any(cell.strip() for cell in row)]


def _cell(row: list[str], index: int, default: str = "") -> str:
    return row[index].strip() if len(row) > index else default


def parse_legacy_trays(text: str) -> list[dict[str, Any]]:
    """Unpack ``A1:Bambu PLA Basic:#00AE42:148.71g:1.966 | EXT:...``.

    Fields are label, material, colour, weight, cost. The unit price was never
    stored, so it is recovered from cost and weight where both are present.
    """
    out: list[dict[str, Any]] = []
    if not text or text.strip().lower() in ("", "unknown", "none"):
        return out

    for chunk in text.split("|"):
        raw = chunk.strip()
        if not raw:
            continue
        parts = [p.strip() for p in raw.split(":")]
        if len(parts) < 4:
            # Unrecognised shape — keep the text rather than throw it away.
            out.append({"label": raw, "name": "", "color": "", "weight": 0.0,
                        "price": 0.0, "cost": 0.0})
            continue

        weight = as_float(parts[3].rstrip("gG "))
        cost = as_float(parts[4]) if len(parts) > 4 else 0.0
        # Approximate: the legacy cost was stored rounded, so this lands within
        # a fraction of a percent of the price actually charged at the time.
        price = round(cost / weight * 1000.0, 2) if weight > 0 and cost > 0 else 0.0
        out.append(
            {
                "label": parts[0],
                "name": parts[1],
                "color": normalise_colour(parts[2]) if parts[2] else "",
                "weight": round(weight, 3),
                "price": price,
                "cost": round(cost, 4),
            }
        )
    return out


def read_legacy_tags(path: str) -> list[dict[str, Any]]:
    """Read a 5- or 6-column tag file, with or without a header row."""
    rows = _rows(path)
    if rows and rows[0] and rows[0][0].strip().lower() in ("filament", "filament type"):
        rows = rows[1:]

    tags: list[dict[str, Any]] = []
    for row in rows:
        filament = _cell(row, 0)
        serial = _cell(row, 3)
        if not filament and not serial:
            continue
        tags.append(
            {
                "filament": filament,
                "color_code": normalise_colour(_cell(row, 1)),
                "color_name": _cell(row, 2),
                "serial": serial,
                "cost_per_kg": as_float(_cell(row, 4)),
                # Column absent on the original 5-column file: that means enabled.
                "disabled": is_disabled(_cell(row, 5)),
                "serial_2": _cell(row, 6),
            }
        )
    return tags


def read_legacy_jobs(path: str) -> list[dict[str, Any]]:
    """Read the 16-column job log, dropping the derived per-100g column."""
    rows = _rows(path)
    if rows and _cell(rows[0], 0).lower() == "timestamp":
        rows = rows[1:]

    jobs: list[dict[str, Any]] = []
    for row in rows:
        if not _cell(row, 0):
            continue

        # Files written before the column was added are one short; anything at
        # or past the drop index shifts back by one only on the full-width rows.
        wide = len(row) >= LEGACY_JOB_COLUMNS
        cover_i, trays_i = (14, 15) if wide else (13, 14)

        jobs.append(
            {
                "timestamp": _cell(row, 0),
                "job": _cell(row, 1),
                "print_time": _cell(row, 2),
                "print_time_min": as_float(_cell(row, 3)),
                "layers": as_float(_cell(row, 4)),
                "weight_g": as_float(_cell(row, 5)),
                "length_m": as_float(_cell(row, 6)),
                "nozzle_size": _cell(row, 7),
                "nozzle_type": _cell(row, 8),
                "energy_kwh": as_float(_cell(row, 9)),
                "filament_cost": as_float(_cell(row, 10)),
                "power_cost": as_float(_cell(row, 11)),
                "total_cost": as_float(_cell(row, 12)),
                "cover": _cell(row, cover_i),
                "trays": parse_legacy_trays(_cell(row, trays_i)),
            }
        )
    return jobs


def import_files(
    store: BambuCostsStore,
    tags_path: str | None,
    jobs_path: str | None,
    covers_path: str | None,
    replace: bool,
) -> dict[str, int]:
    """Bring legacy files into this entry's store. Returns per-item counts."""
    result = {"tags": 0, "jobs": 0, "covers": 0, "covers_missing": 0}
    store.ensure()

    if tags_path:
        incoming = read_legacy_tags(tags_path)
        if replace:
            merged = incoming
        else:
            merged = store.read_tags()
            known = {t["serial"].strip().lower() for t in merged if t["serial"]}
            merged = merged + [
                t for t in incoming if t["serial"].strip().lower() not in known
            ]
        store.write_tags(merged)
        result["tags"] = len(incoming)

    if jobs_path:
        incoming_jobs = read_legacy_jobs(jobs_path)
        existing_stamps: set[str] = set()
        if replace:
            if os.path.exists(store.jobs_path):
                os.remove(store.jobs_path)
            store.ensure()
        else:
            # Re-importing the same file must not duplicate rows.
            existing_stamps = {str(j["ts"]) for j in store.read_jobs(limit=0)}
        for job in incoming_jobs:
            if job["timestamp"] in existing_stamps:
                continue
            store.append_job(job)
            result["jobs"] += 1

        if covers_path and os.path.isdir(covers_path):
            os.makedirs(store.covers_path, exist_ok=True)
            for job in incoming_jobs:
                name = job.get("cover")
                if not name:
                    continue
                source = os.path.join(covers_path, name)
                if not os.path.isfile(source):
                    result["covers_missing"] += 1
                    continue
                try:
                    shutil.copyfile(source, os.path.join(store.covers_path, name))
                    result["covers"] += 1
                except OSError as err:
                    _LOGGER.warning("Could not copy cover %s: %s", name, err)
                    result["covers_missing"] += 1

    return result
