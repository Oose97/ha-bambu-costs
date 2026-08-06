"""Constants for the Bambu Print Costs integration.

Every public name here is deliberately distinct from the hand-rolled YAML /
shell_command / custom-card setup this replaces, so both can run side by side
while migrating.
"""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "bambu_costs"

PLATFORMS: Final = ["button", "number", "sensor"]

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
CONF_COVER_IMAGE: Final = "cover_image"
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

DEFAULT_NAME: Final = "Bambu Costs"
DEFAULT_ELECTRICITY_PRICE: Final = 0.25
DEFAULT_FILAMENT_PRICE: Final = 20.0
DEFAULT_CURRENCY: Final = "EUR"

# Slot definitions are entered as "Attribute", "Attribute|Label" or
# "Attribute|Label|tray_entity_id".
SLOT_SEPARATOR: Final = "|"

# print_weight per-slot attributes rarely sum to exactly the reported total.
# Anything above this (in grams) is treated as filament from an un-tracked
# source — an external spool — rather than as rounding noise.
EXTERNAL_TOLERANCE_G: Final = 0.1

# ── services ─────────────────────────────────────────────────────────────────
SERVICE_WRITE_TAGS: Final = "write_tags"
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

# How often the cost accumulator ticks when nothing else moves. Accrual is
# computed from elapsed time, so this only controls freshness, not accuracy.
COST_TICK_SECONDS: Final = 60

# tag_uid values that mean "no spool here" rather than naming one. The printer
# reports the all-zero UID for a tray it can see but cannot read a tag from.
EMPTY_TAG_UIDS: Final = frozenset(
    {"", "none", "unknown", "unavailable", "0000000000000000"}
)

ATTR_ENTRY_ID: Final = "entry_id"
ATTR_TAGS: Final = "tags"
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
