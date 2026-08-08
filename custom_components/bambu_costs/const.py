"""Constants for the Bambu Print Costs integration.

Every public name here is deliberately distinct from the hand-rolled YAML /
shell_command / custom-card setup this replaces, so both can run side by side
while migrating.
"""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "bambu_costs"

PLATFORMS: Final = ["button", "number", "sensor", "switch"]

# URLs the integration serves.
URL_CARDS: Final = "/bambu-costs-cards"
URL_COVERS: Final = "/bambu-costs-covers"

# On-disk layout: <config>/bambu_costs/<entry_id>/{tags.csv,jobs.csv,covers/}
DATA_DIR: Final = "bambu_costs"
TAGS_FILE: Final = "tags.csv"
JOBS_FILE: Final = "jobs.csv"
COVERS_DIR: Final = "covers"

# ── config keys ──────────────────────────────────────────────────────────────
CONF_PRINT_WEIGHT: Final = "print_weight"
CONF_PRINT_STATUS: Final = "print_status"
CONF_TASK_NAME: Final = "task_name"
# Timestamp sensors, used only when the duration could not be measured live —
# a job whose start Home Assistant never saw (restart, outage).
CONF_START_TIME: Final = "start_time"
CONF_END_TIME: Final = "end_time"
# Log finished jobs without needing an automation to call log_job.
CONF_AUTO_LOG: Final = "auto_log"
CONF_COVER_IMAGE: Final = "cover_image"
CONF_CAMERA: Final = "camera_entity"
CONF_LAYERS: Final = "layers"
CONF_LENGTH: Final = "print_length"
CONF_NOZZLE_SIZE: Final = "nozzle_size"
CONF_NOZZLE_TYPE: Final = "nozzle_type"
CONF_SLOTS: Final = "slots"
CONF_ENERGY_SENSORS: Final = "energy_sensors"
CONF_POWER_SENSORS: Final = "power_sensors"
CONF_ELECTRICITY_PRICE: Final = "electricity_price"
CONF_ELECTRICITY_PRICE_ENTITY: Final = "electricity_price_entity"
CONF_DEFAULT_FILAMENT_PRICE: Final = "default_filament_price"
CONF_CURRENCY: Final = "currency"
# Known filament type names, used by the jobs card to shorten what the log
# shows: a stored value containing one of these — whatever brand precedes
# it — displays as just the type. Display only; nothing stored changes.
CONF_FILAMENT_TYPES: Final = "filament_types"
# Whether a scanned spool whose colour the Bambu palette does not know may
# be named via the color-names web API (api.color.pizza). One tiny GET per
# newly scanned unknown spool; off, or offline, the row says Unknown Color.
CONF_COLOR_NAME_API: Final = "color_name_api"

DEFAULT_NAME: Final = "Bambu Costs"
DEFAULT_ELECTRICITY_PRICE: Final = 0.25
DEFAULT_FILAMENT_PRICE: Final = 20.0
DEFAULT_CURRENCY: Final = "EUR"

# The Bambu lineup as shipped; the options flow lets it be edited, so a new
# SKU (or a third-party type worth matching) is a settings change, not an
# update. An empty option falls back to this list.
DEFAULT_FILAMENT_TYPES: Final = (
    "Support for PLA/PETG", "Support for ABS", "Support for PA/PET",
    "PLA Aero", "PLA Basic", "PLA Dynamic", "PLA Galaxy", "PLA Glow", "PLA Lite",
    "PLA Marble", "PLA Matte", "PLA Metal", "PLA Pure", "PLA Silk+", "PLA Silk",
    "PLA Sparkle", "PLA Tough+", "PLA Tough", "PLA Translucent", "PLA Wood", "PLA-CF",
    "PETG Basic", "PETG HF", "PETG Translucent", "PETG-CF",
    "ABS-GF", "ABS", "ASA Aero", "ASA-CF", "ASA", "PC FR", "PC",
    "PAHT-CF", "PA6-CF", "PA6-GF", "PA-CF", "PET-CF", "PPA-CF", "PPS-CF",
    "TPU for AMS", "TPU 95A HF", "TPU 95A", "TPU 90A", "TPU 85A", "TPU",
    "PVA", "PETG", "PLA",
)

# Slot definitions are entered as "Attribute", "Attribute|Label" or
# "Attribute|Label|tray_entity_id".
SLOT_SEPARATOR: Final = "|"

# print_weight per-slot attributes rarely sum to exactly the reported total.
# Anything above this (in grams) is treated as filament from an un-tracked
# source — an external spool — rather than as rounding noise.
EXTERNAL_TOLERANCE_G: Final = 0.1

# ── services ─────────────────────────────────────────────────────────────────
SERVICE_WRITE_TAGS: Final = "write_tags"
SERVICE_WRITE_JOBS: Final = "write_jobs"
SERVICE_SET_TAG_PRICE: Final = "set_tag_price"
SERVICE_LOG_JOB: Final = "log_job"
SERVICE_REFRESH: Final = "refresh"
SERVICE_IMPORT_LEGACY: Final = "import_legacy"
SERVICE_SYNC_SLOT_PRICES: Final = "sync_slot_prices"

# Print-status values treated as "a job just started". Slot prices are synced
# from the tag library on the transition into one of these.
RUNNING_STATES: Final = frozenset({"running", "printing"})

# Terminal states. Prices are re-mirrored here too, so what the dashboard shows
# after a job matches what was actually loaded for it.
FINISHED_STATES: Final = frozenset({"finish", "finished", "failed"})

# Coming into `running` FROM one of these is a job resuming — a pause, or a
# recovery from a mid-print error such as an AMS jam — not a new job. Only a
# genuinely new job may discard the remembered per-slot split.
RESUME_STATES: Final = frozenset({"pause", "paused", "failed"})

# States meaning Home Assistant lost sight of the printer, rather than a state
# the printer reported about itself. Transitions out of these are ambiguous:
# the printer re-announces whatever it is doing now, which may be a job that
# was already running before contact was lost, or one that began unobserved.
DISCONNECTED_STATES: Final = frozenset(
    {"unavailable", "unknown", "offline", "none", ""}
)

# Device-registry manufacturer the printer setup step is narrowed to. Matches
# what ha-bambulab registers its devices under, and what a fork of it keeps —
# unlike the integration domain, which a rename would change.
PRINTER_MANUFACTURER: Final = "Bambu Lab"

# How often the cost accumulator ticks when nothing else moves. Accrual is
# computed from elapsed time, so this only controls freshness, not accuracy.
COST_TICK_SECONDS: Final = 60

# How far the metered figure may exceed the integrated one before the integral
# is treated as having lost a stretch rather than merely disagreeing. Integrating
# power follows a moving tariff that a flat price cannot, so some disagreement is
# normal and expected; a reporting gap is not subtle.
POWER_COST_TOLERANCE: Final = 0.25

# Average draw above which an energy delta is a counter discontinuity — the
# energy sensors were repointed, a meter reset, or a counter rolled over —
# rather than consumption. Set well clear of a printer plus AMS plus a dryer
# all drawing flat out, so only genuine nonsense trips it.
MAX_PLAUSIBLE_WATTS: Final = 3000.0

# tag_uid values that mean "no spool here" rather than naming one. The printer
# reports the all-zero UID for a tray it can see but cannot read a tag from.
EMPTY_TAG_UIDS: Final = frozenset(
    {"", "none", "unknown", "unavailable", "0000000000000000"}
)

ATTR_ENTRY_ID: Final = "entry_id"
ATTR_TAGS: Final = "tags"
ATTR_ROWS: Final = "rows"
ATTR_SERIAL: Final = "serial"
ATTR_PRICE: Final = "price"

# ── number entities that always exist (per-slot prices are added on top) ──────
# key, translation/name, unit, min, max, step, default
NUMBER_DEFS: Final = (
    ("default_filament_price", "Default filament price", "{currency}/kg", 0, 1000, 0.01, None),
    ("electricity_price", "Electricity price", "{currency}/kWh", 0, 10, 0.0001, None),
    ("last_print_cost", "Last print cost", "{currency}", 0, 100000, 0.01, 0.0),
    ("last_print_filament_cost", "Last print filament cost", "{currency}", 0, 100000, 0.01, 0.0),
    ("last_print_power_cost", "Last print power cost", "{currency}", 0, 100000, 0.01, 0.0),
    ("total_filament_used", "Total filament used", "g", 0, 100000000, 0.01, 0.0),
    ("total_cost", "Total cost", "{currency}", 0, 10000000, 0.01, 0.0),
    ("energy_at_print_start", "Energy at print start", "kWh", 0, 10000000, 0.0001, 0.0),
    ("cost_at_print_start", "Cost total at print start", "{currency}", 0, 10000000, 0.0001, 0.0),
    ("cost_at_print_end", "Cost total at print end", "{currency}", 0, 10000000, 0.0001, 0.0),
    ("last_idle_cost", "Last idle cost", "{currency}", 0, 100000, 0.0001, 0.0),
)

SLOT_PRICE_PREFIX: Final = "filament_price_"
