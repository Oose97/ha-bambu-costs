"""CSV persistence for Bambu Print Costs.

All file access is synchronous and must be called from the executor. Both files
carry a header row and are written with :mod:`csv`, so values containing commas
or quotes are handled by the writer instead of being stripped at the call site.
"""

from __future__ import annotations

import csv
import json
import logging
import os
import shutil
import tempfile
from typing import Any

from .const import COVERS_DIR, JOBS_FILE, TAGS_FILE

_LOGGER = logging.getLogger(__name__)

# serial_2 is appended rather than slotted next to serial: a file written
# before it existed has six columns, and appending keeps those readable.
TAG_FIELDS = [
    "filament", "color_code", "color_name", "serial", "cost_per_kg", "disabled", "serial_2",
]

JOB_FIELDS = [
    "timestamp",
    "job",
    "print_time",
    "print_time_min",
    "layers",
    "weight_g",
    "length_m",
    "nozzle_size",
    "nozzle_type",
    "energy_kwh",
    "filament_cost",
    "power_cost",
    "total_cost",
    "cover",
    "trays",
]

_TRUTHY = {"1", "true", "yes", "on", "disabled"}


def is_disabled(value: Any) -> bool:
    """Interpret the optional disabled column leniently.

    Missing, blank or unrecognised means enabled — a tag is never hidden by
    accident just because the column was hand-edited into an odd shape.
    """
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in _TRUTHY


def as_float(value: Any, default: float = 0.0) -> float:
    """Parse a number tolerantly, accepting both decimal separators."""
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "").strip().replace(" ", "")
    if not text:
        return default
    if "," in text and "." in text:
        text = text.replace(",", "")
    else:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return default


def normalise_colour(value: Any) -> str:
    """Return #RRGGBB, dropping any alpha the integration reports."""
    text = str(value or "").strip().lstrip("#")
    if len(text) >= 6:
        try:
            int(text[:6], 16)
        except ValueError:
            return "#808080"
        return "#" + text[:6].upper()
    return "#808080"


class BambuCostsStore:
    """Owns the on-disk files for one config entry."""

    def __init__(self, root: str) -> None:
        self.root = root
        self.tags_path = os.path.join(root, TAGS_FILE)
        self.jobs_path = os.path.join(root, JOBS_FILE)
        self.covers_path = os.path.join(root, COVERS_DIR)

    # ── setup ────────────────────────────────────────────────────────────────
    def ensure(self) -> None:
        """Create the directory tree and both files if they are missing."""
        os.makedirs(self.covers_path, exist_ok=True)
        if not os.path.exists(self.tags_path):
            self._write_rows(self.tags_path, TAG_FIELDS, [])
        if not os.path.exists(self.jobs_path):
            self._write_rows(self.jobs_path, JOB_FIELDS, [])

    # ── tags ─────────────────────────────────────────────────────────────────
    def read_tags(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for raw in self._read_rows(self.tags_path, TAG_FIELDS):
            filament = (raw.get("filament") or "").strip()
            serial = (raw.get("serial") or "").strip()
            if not filament and not serial:
                continue
            rows.append(
                {
                    "filament": filament,
                    "color_code": normalise_colour(raw.get("color_code")),
                    "color_name": (raw.get("color_name") or "").strip(),
                    "serial": serial,
                    "cost_per_kg": as_float(raw.get("cost_per_kg")),
                    "disabled": is_disabled(raw.get("disabled")),
                    "serial_2": (raw.get("serial_2") or "").strip(),
                }
            )
        return rows

    @staticmethod
    def _serials(tag: dict[str, Any]) -> set[str]:
        """Both tags on a spool, lowercased, blanks dropped."""
        return {
            str(tag.get(k, "")).strip().lower()
            for k in ("serial", "serial_2")
        } - {""}

    def write_tags(self, tags: list[dict[str, Any]]) -> int:
        """Replace the whole tag library, keeping the previous copy as .bak."""
        rows = [
            {
                "filament": str(t.get("filament") or "").strip(),
                "color_code": normalise_colour(t.get("color_code")),
                "color_name": str(t.get("color_name") or "").strip(),
                "serial": str(t.get("serial") or "").strip(),
                "cost_per_kg": f"{as_float(t.get('cost_per_kg')):.2f}",
                "disabled": "true" if is_disabled(t.get("disabled")) else "false",
                "serial_2": str(t.get("serial_2") or "").strip(),
            }
            for t in tags
        ]
        self._backup(self.tags_path)
        self._write_rows(self.tags_path, TAG_FIELDS, rows)
        return len(rows)

    def set_tag_price(self, serial: str, price: float) -> int:
        """Update every row carrying this serial. Returns the number changed."""
        tags = self.read_tags()
        wanted = serial.strip().lower()
        changed = 0
        for tag in tags:
            # Either side of the spool identifies it.
            if wanted in self._serials(tag):
                tag["cost_per_kg"] = price
                changed += 1
        if changed:
            self.write_tags(tags)
        return changed

    def add_tag_if_new(self, tag: dict[str, Any]) -> bool:
        """Append a scanned tag when its serial is not already known.

        A serial already named as some row's second tag counts as known, so
        scanning the other side of a paired spool does not create a duplicate.
        """
        serial = str(tag.get("serial") or "").strip()
        if not serial:
            return False
        tags = self.read_tags()
        if any(serial.lower() in self._serials(t) for t in tags):
            return False
        tags.append(tag)
        self.write_tags(tags)
        return True

    # ── jobs ─────────────────────────────────────────────────────────────────
    def read_jobs(self, limit: int = 200) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for raw in self._read_rows(self.jobs_path, JOB_FIELDS):
            if not (raw.get("timestamp") or "").strip():
                continue
            try:
                trays = json.loads(raw.get("trays") or "[]")
            except (ValueError, TypeError):
                trays = []
            rows.append(
                {
                    "ts": raw.get("timestamp", ""),
                    "job": raw.get("job", ""),
                    "time": raw.get("print_time", ""),
                    "mins": as_float(raw.get("print_time_min")),
                    "layers": as_float(raw.get("layers")),
                    "weight": as_float(raw.get("weight_g")),
                    "length": as_float(raw.get("length_m")),
                    "nozzle": raw.get("nozzle_size", ""),
                    "nozzle_type": raw.get("nozzle_type", ""),
                    "kwh": as_float(raw.get("energy_kwh")),
                    "f_cost": as_float(raw.get("filament_cost")),
                    "p_cost": as_float(raw.get("power_cost")),
                    "cost": as_float(raw.get("total_cost")),
                    "cover": raw.get("cover", ""),
                    "trays": trays if isinstance(trays, list) else [],
                }
            )
        return rows[-limit:] if limit else rows

    def append_job(self, row: dict[str, Any]) -> None:
        payload = {field: row.get(field, "") for field in JOB_FIELDS}
        if isinstance(payload.get("trays"), (list, dict)):
            payload["trays"] = json.dumps(payload["trays"], separators=(",", ":"))
        exists = os.path.exists(self.jobs_path)
        with open(self.jobs_path, "a", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=JOB_FIELDS)
            if not exists or os.path.getsize(self.jobs_path) == 0:
                writer.writeheader()
            writer.writerow(payload)

    # ── covers ───────────────────────────────────────────────────────────────
    def save_cover(self, content: bytes, name: str) -> str:
        """Store a job cover image, shrinking it when Pillow is available."""
        safe = "".join(c for c in name if c.isalnum() or c in "-_") or "cover"
        filename = f"{safe}.jpg"
        target = os.path.join(self.covers_path, filename)
        os.makedirs(self.covers_path, exist_ok=True)

        try:
            import io

            from PIL import Image  # noqa: PLC0415 — optional, ships with HA core

            image = Image.open(io.BytesIO(content))
            image = image.convert("RGB")
            image.thumbnail((320, 320))
            image.save(target, "JPEG", quality=72, optimize=True)
        except Exception:  # noqa: BLE001 — any failure falls back to the original
            _LOGGER.debug("Pillow unavailable or failed; storing cover unresized")
            with open(target, "wb") as handle:
                handle.write(content)
        return filename

    # ── internals ────────────────────────────────────────────────────────────
    def _read_rows(self, path: str, fields: list[str]) -> list[dict[str, Any]]:
        if not os.path.exists(path):
            return []
        with open(path, "r", encoding="utf-8", newline="") as handle:
            sample = handle.readline()
            handle.seek(0)
            # Tolerate a headerless file so a hand-made CSV still loads.
            has_header = sample.split(",")[0].strip().lower() == fields[0]
            if has_header:
                return list(csv.DictReader(handle))
            return list(csv.DictReader(handle, fieldnames=fields))

    def _write_rows(self, path: str, fields: list[str], rows: list[dict[str, Any]]) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline="", dir=os.path.dirname(path), delete=False
        )
        try:
            with handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)
            os.replace(handle.name, path)
        except BaseException:
            with suppress_errors():
                os.unlink(handle.name)
            raise

    def _backup(self, path: str) -> None:
        if os.path.exists(path) and os.path.getsize(path) > 0:
            with suppress_errors():
                shutil.copyfile(path, f"{path}.bak")


class suppress_errors:  # noqa: N801 — tiny context manager, reads better lowercase
    """Swallow cleanup errors so they never mask the original exception."""

    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type, exc, tb) -> bool:
        return exc_type is not None and issubclass(exc_type, OSError)
