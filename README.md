# Bambu Print Costs

A Home Assistant integration that works out what a 3D print actually cost — filament per
AMS slot, electricity, and a per-job history — and ships the Lovelace cards to manage it.

It replaces a pile of `command_line` sensors, `shell_command` entries, shell scripts,
`input_number` helpers and manually-registered card resources with one config entry.

**Nothing is hard-coded.** Every sensor it reads is chosen during setup, and the filament
slots are free-form, so any AMS layout — or none — works.

---

## What you get

### Sensors

| Entity | What it holds |
| --- | --- |
| `sensor.<name>_filament_breakdown` | Cost of the job on the printer now. The `slots` attribute has the unrounded per-slot rows. |
| `sensor.<name>_session_filament_cost` | The same figure rounded for display. |
| `sensor.<name>_tag_library` | Your filament tag library. State is the row count; `data` holds the rows. |
| `sensor.<name>_job_log` | Logged jobs. State is the row count; `data` holds the rows. |

### Numbers

Plain writable numbers — no `input_number` helpers needed. Set them by hand in the UI or
from an automation with `number.set_value`. Values survive restarts.

- `number.<name>_default_filament_price` — fallback price per kg
- `number.<name>_<slot>_filament_price` — one per configured slot
- `number.<name>_electricity_price` — per kWh, the fallback when no price sensor is set
- `number.<name>_last_print_cost`, `_last_print_filament_cost`, `_last_print_power_cost`
- `number.<name>_total_filament_used`, `_total_cost` — lifetime running totals
- `number.<name>_energy_at_print_start` — snapshot taken when a print begins
- `number.<name>_filter_change_due`

### Services

| Service | Does |
| --- | --- |
| `bambu_costs.log_job` | Appends the finished job, captures the cover image, advances the totals. Anything you do not pass is read from the configured sensors. |
| `bambu_costs.write_tags` | Replaces the tag library. Previous file kept as `tags.csv.bak`. |
| `bambu_costs.set_tag_price` | Updates the price on every tag with a given RFID serial. |
| `bambu_costs.refresh` | Re-reads the CSVs from disk. |
| `bambu_costs.sync_slot_prices` | Copies the loaded spool's tag price into each slot's price number. |
| `bambu_costs.import_legacy` | Pulls tags, job history and cover images in from the pre-integration CSVs. |

Pass `entry_id` only if you have set up more than one printer.

### Cards

Registered automatically — no Lovelace resource to add, and no `?v=` to bump. The
integration's version is appended to every URL, so upgrading busts the browser cache
on its own.

- `custom:bambu-costs-tags-editor` — editable, reorderable filament tag library
- `custom:bambu-costs-jobs-table` — sortable, paginated print history
- `custom:bambu-costs-calculator` — manual quote: filament, runtime, margin, VAT

---

## Requirements

Home Assistant 2024.12 or newer, and a source of printer sensors — in practice the
[ha-bambulab](https://github.com/greghesp/ha-bambulab) integration, which is what this was
built against and what the setup screen expects to find.

That dependency is declared as `after_dependencies`, not `dependencies`: if `bambu_lab` is
installed it loads first so its sensors exist before the first refresh, but this
integration will still set up without it. Nothing here reads the Bambu integration
directly — it only reads whichever entities you point it at — so it works with a fork, or
with an entirely different printer integration, as long as something exposes a per-slot
print weight sensor.

## Install

**HACS** → three-dot menu → *Custom repositories* → add this repo as an **Integration**,
then download it and restart Home Assistant.

**No GitHub release is needed.** HACS falls back to the default branch when a repository
has no releases, and nothing here blocks that: `hide_default_branch` is not set, and
`zip_release` is deliberately left off — turning it on without a published zip is what
makes downloads hang. HACS spots new commits on the branch, so updates still surface
normally.

If you would rather pin versions, bump `version` in `custom_components/bambu_costs/manifest.json`
and tag a release; HACS switches to using releases as soon as one exists.

**Manually**: copy `custom_components/bambu_costs` into your `config/custom_components/`
and restart.

Then *Settings → Devices & Services → Add Integration → Bambu Print Costs*.

## Setup

**Step 1 — sensors.** Only the print weight and print status sensors are required. The
rest (job name, layers, length, nozzle size and type, cover image) enrich the job log.

**Step 2 — slots and rates.** Add one entry per filament source, using the attribute name
exactly as the print weight sensor reports it:

```
AMS 1 Tray 1
AMS 1 Tray 2|A2
AMS HT 1|HT|sensor.printer_ams_ht_tray_1
```

- **First part** — the `print_weight` attribute name. Matched verbatim, never guessed:
  these names have changed across printer-integration releases before, and a guess that
  silently misses is worse than a blank.
- **Second part** *(optional)* — a short label for the dashboard.
- **Third part** *(optional)* — the tray sensor. Supplies the colour and material for the
  job log, and its `tag_uid` prices the slot straight from your tag library.

Leave the list empty if you do not use an AMS; everything is then priced at the default.

## Electricity price

Set **Electricity price sensor** to a sensor reporting the price per kWh and a variable
tariff is followed automatically — `sensor.electricity_price` at `0.22986 EUR/kWh` is the
shape this expects. The fixed **Electricity price** number stays as the fallback, used
whenever no sensor is configured or the sensor reads `unknown`/`unavailable`/non-numeric.

Negative prices are passed through rather than filtered, since spot tariffs can go
negative. The sensor's value is taken as-is, so it must already be per kWh in your
currency — point it at a template sensor if yours reports ct/kWh or EUR/MWh.

> **Caveat with spot pricing:** the price is read once, when the job is logged, and applied
> to the whole print. For a long print on a tariff that moves hourly that is an
> approximation — the true cost is the price integrated over the print. If you need it
> exact, pass `power_cost` explicitly to `bambu_costs.log_job` from something that tracks
> cost over time, such as a `utility_meter` with tariffs.

## How a slot gets its price

In order of precedence:

1. The **tag library**, matched on the `tag_uid` the tray reports — the price of the spool
   actually loaded.
2. The slot's own **price number**, if you have set one.
3. The **default filament price**.

Each row in the breakdown carries `price_source` so you can see which applied.

Costing never depends on the slot price entities being current — the tag price is resolved
live. For visibility they are also written when a print starts: on the transition of the
print status sensor into `running`, every slot whose tray reports a tag the library knows
has its price number updated. A slot with no tray, no tag, or an unknown serial is left
alone, so a hand-set price is never clobbered. `bambu_costs.sync_slot_prices` does the
same on demand.

Filament the printer counted that no configured slot claimed — an external spool, or a
slot whose attribute name drifted — becomes an `External` row priced at the default,
rather than being dropped. Mixed AMS + external jobs therefore total correctly.

## Surviving a restart mid-print

A print weight sensor typically keeps its total across a Home Assistant restart but
loses the per-slot attributes until the next print begins. Left alone, the whole job
would fall through to the External branch and be repriced at the default — a
plausible-looking but wrong number, quietly written into the job log.

So the last breakdown computed from real per-slot data is persisted with the sensor. If
the attributes disappear while the job name and total weight still match that snapshot,
the remembered split is used and the breakdown carries `restored: true`.

It is deliberately conservative. A different job name or a changed total rejects the
snapshot, live attributes always win over it, an External-only result is never
remembered as good, and the snapshot is dropped the moment a new print starts so it can
never be applied to different filament. Prices are kept as they were rather than
re-resolved — the tray sensors lose their `tag_uid` in the same restart, so recomputing
would reintroduce the fallback this exists to avoid.

## Logging a finished job

```yaml
triggers:
  - trigger: state
    entity_id: sensor.printer_print_status
    to: finished
actions:
  - action: bambu_costs.log_job
    data:
      print_time_min: "{{ states('sensor.printer_print_time') | float(0) }}"
```

Take the energy snapshot when a print starts, so the job's electricity is measured
against it:

```yaml
triggers:
  - trigger: state
    entity_id: sensor.printer_print_status
    to: running
actions:
  - action: number.set_value
    target:
      entity_id: number.bambu_costs_energy_at_print_start
    data:
      value: >-
        {{ (states('sensor.printer_socket_energy') | float(0))
         + (states('sensor.ams_socket_energy')     | float(0)) }}
```

## Card examples

```yaml
type: custom:bambu-costs-tags-editor
entity: sensor.bambu_costs_tag_library
```

```yaml
type: custom:bambu-costs-jobs-table
entity: sensor.bambu_costs_job_log
page_size: 20
```

```yaml
type: custom:bambu-costs-calculator
entity: sensor.bambu_costs_tag_library
rate_per_minute: 0.0008
margin_percent: 30
vat_percent: 21
```

## Files on disk

```
config/bambu_costs/<entry_id>/tags.csv
config/bambu_costs/<entry_id>/tags.csv.bak
config/bambu_costs/<entry_id>/jobs.csv
config/bambu_costs/<entry_id>/covers/*.jpg
```

Both CSVs have a header row and are written with a real CSV writer, so commas and quotes
inside a value are quoted rather than stripped. A headerless file still loads, so you can
drop an existing tag list in unchanged.

Covers are served at `/bambu-costs-covers/`. Nothing else under `config/` is exposed.

The bulky `data` and `slots` attributes are excluded from the recorder automatically —
no hand-written `recorder:` exclusion needed.

## Importing existing CSVs

Call `bambu_costs.import_legacy` from *Developer Tools → Actions*:

```yaml
action: bambu_costs.import_legacy
data:
  tags_path: /config/www/bambu_tags.csv
  jobs_path: /config/www/bambu_jobs_log.csv
  covers_path: /config/www/images/bambu_jobs
```

It returns how many of each it took. What it handles:

- **Tags** — 5-column files (no `disabled` column, so everything imports enabled) and
  6-column ones, with or without a header row.
- **Jobs** — the 16-column layout, including dropping the derived `eur_per_100g` column
  so nothing after it lands in the wrong field.
- **Trays** — `A1:Bambu PLA Basic:#00AE42:148.71g:1.966 | EXT:…` is unpacked into proper
  objects. The unit price was never stored in that format, so it is recovered from cost
  and weight; it lands within a fraction of a percent of what was charged at the time.
- **Covers** — images referenced by the job log are copied in and re-served under the
  integration's own URL.

Blank lines are skipped, and re-running is safe: jobs are matched on timestamp and tags
on serial, so nothing duplicates. Pass `replace: true` to wipe first instead of merging.

You can also just drop a **tags** CSV straight in at
`config/bambu_costs/<entry_id>/tags.csv` — the reader falls back to headerless parsing.
That shortcut does *not* work for the job log, whose columns have changed; use the
service for that.

## Running alongside an existing setup

Every name here is distinct from the YAML/shell setup this grew out of, so both can run
at once while you migrate:

| | Old | New |
| --- | --- | --- |
| Tag sensor | `sensor.bambu_tags` | `sensor.bambu_costs_tag_library` |
| Job sensor | `sensor.bambu_jobs_log` | `sensor.bambu_costs_job_log` |
| Prices | `input_number.3d_printer_*` | `number.bambu_costs_*` |
| Cards | `bambu-tags-editor`, … | `bambu-costs-tags-editor`, … |
| Data | `config/www/bambu_tags.csv` | `config/bambu_costs/<entry>/tags.csv` |
| Writes | `shell_command.*` | `bambu_costs.*` |

## Not included yet

- No dashboard is created for you; the cards are yours to place.
- Tag scanning (appending a newly-seen spool to the library) is not wired to an event yet.
- Idle/standby cost tracking between prints.
