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

from .const import COVERS_DIR, JOBS_FILE, OVERLAY_FILE, TAGS_FILE

_LOGGER = logging.getLogger(__name__)

# serial_2 is appended rather than slotted next to serial: a file written
# before it existed has six columns, and appending keeps those readable.
# tray_uuid — the printer cloud's per-spool id, learned from the tray when a
# spool is loaded — is appended again for the same reason.
TAG_FIELDS = [
    "filament", "color_code", "color_name", "serial", "cost_per_kg", "disabled", "serial_2",
    "tray_uuid",
    # Grams left on the spool, kept current from the cloud filament inventory
    # when one is configured. Blank means "not known", which is different
    # from 0 — an empty spool is knowledge too.
    "remaining_g",
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
    # The printer's finish estimate as it stood when the job began, in the
    # timestamp column's own format — so a row can say how far the actual
    # finish drifted from the plan. Blank for jobs logged before it existed.
    "finish_estimate",
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


def count_spools(tags: list[dict[str, Any]]) -> int:
    """Distinct physical spools behind a list of tag rows.

    A paired spool is two rows naming each other in ``serial_2``, and both
    collapse onto one spool. The reference is followed through either side —
    a hand-edited file where only one row carries the pairing still counts
    the two rows as one spool. A row with no serial at all is a spool whose
    tag was never recorded, and counts by itself.
    """
    # Union-find over serials: every serial a row carries belongs to the same
    # spool, so overlapping serial sets merge into one identity.
    parent: dict[str, str] = {}

    def find(serial: str) -> str:
        while parent[serial] != serial:
            parent[serial] = parent[parent[serial]]
            serial = parent[serial]
        return serial

    bare = 0
    for tag in tags:
        serials = [
            s
            for s in (
                str(tag.get(k) or "").strip().lower() for k in ("serial", "serial_2")
            )
            if s
        ]
        if not serials:
            bare += 1
            continue
        for s in serials:
            parent.setdefault(s, s)
        for s in serials[1:]:
            root, other = find(serials[0]), find(s)
            if root != other:
                parent[other] = root

    return len({find(s) for s in parent}) + bare


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
        self.overlay_path = os.path.join(root, OVERLAY_FILE)
        self.covers_path = os.path.join(root, COVERS_DIR)

    # ── the current job's edits ──────────────────────────────────────────────
    def read_overlay(self) -> dict[str, Any]:
        """The user's mid-print edits — only what they touched, nothing else.

        A missing or unreadable file is an empty overlay: the worst a corrupt
        file can do is forget edits, never break logging.
        """
        try:
            with open(self.overlay_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def write_overlay(self, overlay: dict[str, Any]) -> None:
        """Persist the edits; an empty overlay removes the file."""
        if not overlay:
            with suppress_errors():
                os.remove(self.overlay_path)
            return
        handle = tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=self.root, delete=False
        )
        try:
            with handle:
                json.dump(overlay, handle, separators=(",", ":"))
            os.replace(handle.name, self.overlay_path)
        except BaseException:
            with suppress_errors():
                os.unlink(handle.name)
            raise

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
                    "tray_uuid": (raw.get("tray_uuid") or "").strip(),
                    "remaining_g": (raw.get("remaining_g") or "").strip(),
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
                "tray_uuid": str(t.get("tray_uuid") or "").strip(),
                "remaining_g": ""
                if str(t.get("remaining_g", "")).strip() == ""
                else f"{as_float(t.get('remaining_g')):.0f}",
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

    def set_remaining(self, serial: str, grams: float) -> int:
        """Update remaining grams on every row carrying this serial.

        The tray only names the tag it read, but what remains describes the
        spool — so a pair's two rows move together, matched the same way a
        price push matches. Only actual differences write the file.
        """
        tags = self.read_tags()
        wanted = serial.strip().lower()
        remaining = f"{as_float(grams):.0f}"
        changed = 0
        for tag in tags:
            if wanted in self._serials(tag):
                if str(tag.get("remaining_g", "")).strip() != remaining:
                    tag["remaining_g"] = remaining
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

    def sync_inventory(self, spools: list[dict[str, Any]]) -> dict[str, int]:
        """Fold the cloud filament inventory into the library.

        Two jobs, both keyed on the learned spool id. Every row carrying a
        spool's id gets its ``remaining_g`` refreshed — a pair's two rows and
        clone rows sharing one id alike. A spool whose id no row carries is
        *added*, serial-less, unless an id-less row already matches its
        product and colour — that row is almost certainly the same physical
        spool waiting to learn its id on the next load, and seeding a twin
        for it would litter the library. Each spool dict carries a prepared
        ``seed`` row for exactly this case.

        Only actual differences write the file, so this can run on every
        inventory update without churning it.
        """
        tags = self.read_tags()
        updated = 0
        seeded = 0
        changed = False

        for spool in spools:
            uuid = str(spool.get("tray_uuid") or "").strip()
            if not uuid or set(uuid) == {"0"}:
                continue
            remaining = f"{as_float(spool.get('remaining_g')):.0f}"

            rows = [
                t
                for t in tags
                if str(t.get("tray_uuid") or "").strip().lower() == uuid.lower()
            ]
            if rows:
                for row in rows:
                    if str(row.get("remaining_g", "")).strip() != remaining:
                        row["remaining_g"] = remaining
                        updated += 1
                        changed = True
                continue

            match_name = str(spool.get("match_name") or "").strip().lower()
            colour = str(spool.get("color_code") or "").strip().upper()
            candidate = any(
                not str(t.get("tray_uuid") or "").strip()
                and minimal_filament(t.get("filament")).lower() == match_name
                and str(t.get("color_code") or "").strip().upper() == colour
                for t in tags
            )
            if candidate:
                continue

            seed = dict(spool.get("seed") or {})
            if not seed:
                continue
            seed["remaining_g"] = remaining
            tags.append(seed)
            seeded += 1
            changed = True

        if changed:
            self.write_tags(tags)
        return {"updated": updated, "seeded": seeded}

    def claim_seeded_row(self, serial: str, tray_uuid: str) -> bool:
        """Give an inventory-seeded row its tag, instead of adding a twin.

        A row seeded from the inventory knows its spool id but no serial —
        the cloud does not carry tag UIDs. The first time that spool is
        actually loaded, the scan would otherwise append a fresh row for it;
        claiming writes the serial onto the seeded row instead, and from
        there it behaves like any scanned spool.
        """
        uuid = str(tray_uuid or "").strip()
        wanted = str(serial or "").strip()
        if not uuid or not wanted or set(uuid) == {"0"}:
            return False
        tags = self.read_tags()
        if any(wanted.lower() in self._serials(t) for t in tags):
            return False
        row = next(
            (
                t
                for t in tags
                if not str(t.get("serial") or "").strip()
                and str(t.get("tray_uuid") or "").strip().lower() == uuid.lower()
            ),
            None,
        )
        if row is None:
            return False
        row["serial"] = wanted
        self.write_tags(tags)
        return True

    def learn_tray_uuid(self, serial: str, tray_uuid: str) -> dict[str, str] | None:
        """Record the cloud's per-spool id on the row this tag belongs to.

        Loading a spool is the one moment both identifiers are visible at
        once — the tag the AMS read and the ``tray_uuid`` the printer reports
        for it — so the mapping is learned here, hands-free. Only a blank is
        ever filled: a value the user typed, corrected or learned before
        stands, so this can run on every load without churning the file.

        The id also pairs rows. A spool carries a tag on each side; when the
        other side is scanned later it lands as its own row, and the shared
        tray_uuid is what betrays the two as one spool — so if both rows have
        an empty ``serial_2``, they are paired on the spot. Rows already
        paired are never touched, which is also what keeps clone-tagged
        spools (several physical spools sharing one cloud id) safe: their
        rows pair to their own other sides, not to each other.

        Returns what changed, or None when nothing did.
        """
        uuid = str(tray_uuid or "").strip()
        wanted = str(serial or "").strip().lower()
        if not uuid or not wanted or set(uuid) == {"0"}:
            return None

        tags = self.read_tags()
        row = next((t for t in tags if wanted in self._serials(t)), None)
        if row is None:
            return None

        changed: dict[str, str] = {}
        if not row.get("tray_uuid"):
            row["tray_uuid"] = uuid
            changed["learned"] = uuid
        elif row["tray_uuid"].strip().lower() != uuid.lower():
            # A different id on file — an edit, or a clone collision. Theirs.
            return None

        # One spool, one id: a row already paired shares the spool with its
        # partner, so a blank on the other side is filled along with it.
        if row.get("serial_2"):
            other = str(row["serial_2"]).strip().lower()
            for t in tags:
                if t is not row and other in self._serials(t) and not t.get("tray_uuid"):
                    t["tray_uuid"] = uuid
                    changed["learned_partner"] = t.get("serial", "")

        if not row.get("serial_2"):
            partner = next(
                (
                    t
                    for t in tags
                    if t is not row
                    and str(t.get("tray_uuid") or "").strip().lower() == uuid.lower()
                    and not t.get("serial_2")
                    and t.get("serial")
                    and t["serial"].strip().lower() not in self._serials(row)
                ),
                None,
            )
            if partner is not None:
                row["serial_2"] = partner["serial"]
                partner["serial_2"] = row["serial"]
                changed["paired_with"] = partner["serial"]

        if not changed:
            return None
        self.write_tags(tags)
        return changed

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
                    "finish_est": (raw.get("finish_estimate") or "").strip(),
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
            "finish_estimate": str(row.get("finish_est") or "").strip(),
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
