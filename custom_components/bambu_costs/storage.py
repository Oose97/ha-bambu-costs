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

# filament_type is appended for the same reason serial_2 is above: files
# written before it existed keep their column order.
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
    "filament_type",
    # Appended for the same reason again. layers_done is how far a failed
    # print got; status is "success" or "failed", blank meaning success so
    # files from before the column read unchanged.
    "layers_done",
    "status",
]


def job_status(value: Any) -> str:
    """Normalise the status column: only an explicit "failed" is a failure."""
    return "failed" if str(value or "").strip().lower() == "failed" else "success"

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


def minimal_filament(name: Any) -> str:
    """A filament product name cut down to what distinguishes it.

    The printer reports full product names ("Bambu PLA Basic"). On a Bambu
    printer the brand prefix carries no information, so it is dropped and the
    job log reads "PLA Basic".
    """
    text = " ".join(str(name or "").split())
    if text.lower().startswith("bambu "):
        text = text[len("bambu "):]
    return text


def distinct_filaments(slots: list[dict[str, Any]]) -> str:
    """The distinct filament types across a job's slots, in slot order.

    Four trays of the same PLA are one entry; a multi-material job lists each
    material once — "PLA Basic, PETG HF". Slots with no name at all (an
    untracked external spool) contribute nothing rather than an empty entry.
    """
    seen: list[str] = []
    for slot in slots:
        name = minimal_filament(slot.get("filament") or slot.get("material"))
        if name and name not in seen:
            seen.append(name)
    return ", ".join(seen)


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
                    "types": (raw.get("filament_type") or "").strip(),
                    "layers_done": as_float(raw.get("layers_done")),
                    "status": job_status(raw.get("status")),
                }
            )
        return rows[-limit:] if limit else rows

    def append_job(self, row: dict[str, Any]) -> None:
        payload = {field: row.get(field, "") for field in JOB_FIELDS}
        if isinstance(payload.get("trays"), (list, dict)):
            payload["trays"] = json.dumps(payload["trays"], separators=(",", ":"))
        self._upgrade_jobs_header()
        exists = os.path.exists(self.jobs_path)
        with open(self.jobs_path, "a", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=JOB_FIELDS)
            if not exists or os.path.getsize(self.jobs_path) == 0:
                writer.writeheader()
            writer.writerow(payload)

    def _upgrade_jobs_header(self) -> None:
        """Bring an older jobs file up to the current column set.

        The jobs file is append-only, so its header is written once and then
        outlives column additions. Appending a wider row under a narrower
        header would silently drop the new columns on read — the reader keys
        rows off the header — so the whole file is rewritten with the current
        header the first time it matters. Headerless files get one too.
        """
        if not os.path.exists(self.jobs_path) or os.path.getsize(self.jobs_path) == 0:
            return
        with open(self.jobs_path, "r", encoding="utf-8", newline="") as handle:
            first = handle.readline().strip()
        if first == ",".join(JOB_FIELDS):
            return
        rows = self._read_rows(self.jobs_path, JOB_FIELDS)
        self._backup(self.jobs_path)
        self._write_rows(
            self.jobs_path, JOB_FIELDS,
            [{field: raw.get(field, "") for field in JOB_FIELDS} for raw in rows],
        )

    def update_jobs(self, edits: list[dict[str, Any]]) -> int:
        """Rewrite edited log rows in place, matched by original timestamp.

        The card only ever sees the tail of the file (``read_jobs`` windows
        it), so a save must not replace the file with what the card holds —
        that would drop every older row. Instead each edited row names the
        timestamp it was loaded with (``orig_ts``), and only the matching file
        rows are swapped out; everything else, including a job the integration
        logged while the edit was open, is carried through untouched.

        A row that cannot be matched means the file changed under the editor,
        and the whole save is refused rather than half-applied.

        An edit carrying ``delete: true`` removes its matched row instead of
        replacing it. The row's cover image is left on disk — a 2 kB file is
        a cheap price for a deletion being recoverable from jobs.csv.bak.
        """
        raw_rows = self._read_rows(self.jobs_path, JOB_FIELDS)

        by_ts: dict[str, list[int]] = {}
        for index, raw in enumerate(raw_rows):
            by_ts.setdefault((raw.get("timestamp") or "").strip(), []).append(index)

        replacements: list[tuple[int, dict[str, Any] | None]] = []
        for edit in edits:
            key = str(edit.get("orig_ts") or edit.get("ts") or "").strip()
            queue = by_ts.get(key)
            if not queue:
                raise LookupError(
                    f"No logged job with timestamp '{key}' — the log changed on "
                    "disk; reload the table and redo the edit"
                )
            # Duplicate timestamps pair up in file order, so two same-second
            # rows each get their own edit instead of both taking the first.
            converted = None if edit.get("delete") else self._job_to_csv(edit)
            replacements.append((queue.pop(0), converted))

        dropped: set[int] = set()
        for index, converted in replacements:
            if converted is None:
                dropped.add(index)
            else:
                raw_rows[index] = converted

        self._backup(self.jobs_path)
        self._write_rows(
            self.jobs_path, JOB_FIELDS,
            [
                {field: raw.get(field, "") for field in JOB_FIELDS}
                for index, raw in enumerate(raw_rows)
                if index not in dropped
            ],
        )
        return len(replacements)

    @staticmethod
    def _job_to_csv(row: dict[str, Any]) -> dict[str, Any]:
        """Map a row from the sensor's shape back onto the CSV columns."""
        trays = row.get("trays", [])
        return {
            # An emptied timestamp falls back to the original: a blank one
            # would make the row invisible to read_jobs, deleting it in effect.
            "timestamp": str(row.get("ts") or row.get("orig_ts") or "").strip(),
            "job": str(row.get("job") or "").strip(),
            "print_time": str(row.get("time") or "").strip(),
            "print_time_min": round(as_float(row.get("mins")), 2),
            "layers": as_float(row.get("layers")),
            "weight_g": round(as_float(row.get("weight")), 3),
            "length_m": as_float(row.get("length")),
            "nozzle_size": str(row.get("nozzle") or "").strip(),
            "nozzle_type": str(row.get("nozzle_type") or "").strip(),
            "energy_kwh": round(as_float(row.get("kwh")), 4),
            "filament_cost": round(as_float(row.get("f_cost")), 4),
            "power_cost": round(as_float(row.get("p_cost")), 4),
            "total_cost": round(as_float(row.get("cost")), 4),
            "cover": str(row.get("cover") or "").strip(),
            "trays": json.dumps(trays, separators=(",", ":"))
            if isinstance(trays, (list, dict))
            else str(trays or "[]"),
            "filament_type": str(row.get("types") or "").strip(),
            "layers_done": as_float(row.get("layers_done")),
            "status": job_status(row.get("status")),
        }

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
