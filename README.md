# Bambu Print Costs

<img src="brand/icon.svg" width="96" alt="">

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
| `sensor.<name>_cost_rate` | What the machine is costing per hour right now — power × price. |
| `sensor.<name>_cost_total` | Everything it has cost to run, printing or idle. Restored across restarts. |
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
- `number.<name>_cost_at_print_start`, `_cost_at_print_end` — markers in the running total
- `number.<name>_last_idle_cost` — electricity burnt between the last two prints

### Buttons

- `button.<name>_charge_filament_to_totals` — adds the current job's filament cost and
  weight to the lifetime totals. For a print that failed part-way. Deliberately manual:
  the printer reports the job's *planned* weight, so charging a failure automatically
  would bill a first-layer failure in full. The last press is recorded in the button's
  attributes so a mis-press is visible.

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

### Icon

Shipped with the integration in `custom_components/bambu_costs/brand/`, so it shows in
Settings → Devices & Services with no brands-repository submission. Requires Home
Assistant 2026.3 or newer; on older versions the default placeholder is used instead.

### Cards

Registered automatically as Lovelace module resources, with the integration's version
appended so an upgrade busts the browser cache on its own. They show up under
Settings → Dashboards → Resources, and are removed when the last config entry is
deleted. In YAML-mode Lovelace the files are still served — the URLs are logged at
startup for you to add by hand.

- `custom:bambu-costs-tags-editor` — editable, reorderable filament tag library. **⚙ Columns**
  hides and reorders columns; that is display only, so a save still writes every field in
  its canonical order. A spool's two tags are kept adjacent and share one drag handle, so
  a pair moves as a unit. Each row's
  **SET** button opens a picker listing every filament price entity — the default first,
  then one per configured slot — so a tag's price can be pushed into whichever slot has
  that spool loaded. The list is resolved from the entity registry, so it follows the
  slot configuration on its own.
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

HACS installs the latest release. `zip_release` is deliberately left off — turning it on
without a published zip is what makes downloads hang — so HACS takes the files from the
release tag.

**Manually**: copy `custom_components/bambu_costs` into your `config/custom_components/`
and restart.

Then *Settings → Devices & Services → Add Integration → Bambu Print Costs*.

## Releasing

`main` is protected: changes land through a pull request that passes Validate.

Releases are cut automatically. Bump `version` in
`custom_components/bambu_costs/manifest.json` as part of the change; once it merges and
Validate passes on `main`, the Release workflow tags `vX.Y.Z` and publishes it with
generated notes. A merge that does not change the version publishes nothing, so
documentation-only changes do not churn out releases.

The manifest is the single source of truth — it is what Home Assistant and HACS actually
read, and the tag follows it rather than the other way round.

## Setup

**Step 1 — pick the printer device.** Everything else is filled in from it: the sensors,
and any AMS slots the printer is currently reporting, each paired with its tray. Leave it
empty to configure by hand.

Entities are matched on their `translation_key`, not on entity-id suffixes, so a renamed
entity is still found — `subtask_name` is displayed as "Task name", which is where
`sensor.…_task_name` comes from, and matching on the key survives that. Slot attribute
names are read off the print weight sensor rather than invented, and a tray is attached
only when the pairing is unambiguous; anything doubtful is listed for you instead.

The catch: the printer only reports per-slot attributes for slots the *current* job uses,
so a discovery run while idle finds no slots and one mid-print finds only the slots in
use. The rest are listed as unpaired trays for you to add. Re-running discovery from the
options later picks up the rest.

**Step 2 — sensors.** Whatever was found, shown so you can correct it before continuing.

**Step 3 — slots and rates.** Add one entry per filament source, using the attribute name
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

## Currency

Set during setup, prefilled with `EUR`, and changeable in the options. It is display-only —
any text works — and flows through the number entities' units, both cost sensors, and the
cards, which pick it up from the integration rather than needing their own setting.

## Electricity price

Set **Electricity price sensor** to a sensor reporting the price per kWh and a variable
tariff is followed automatically — `sensor.electricity_price` at `0.22986 EUR/kWh` is the
shape this expects. The fixed **Electricity price** number stays as the fallback, used
whenever no sensor is configured or the sensor reads `unknown`/`unavailable`/non-numeric.

Negative prices are passed through rather than filtered, since spot tariffs can go
negative. The sensor's value is taken as-is, so it must already be per kWh in your
currency — point it at a template sensor if yours reports ct/kWh or EUR/MWh.

### Cost is integrated, not estimated

Set **Power sensors** and the integration keeps a live cost rate — summed watts × the
current price — and integrates it over time into `cost_total`. Because the rate is re-read
whenever the power or the price moves, and each interval is charged at the rate that
actually applied to it, a tariff that changes mid-print is charged as it changed. That
removes the approximation of multiplying total kWh by the price at the end.

Two consequences fall out of the accumulator running continuously:

- **A print's electricity** is the total's delta between start and finish, so it is exact
  even on a spot tariff. `log_job` uses it whenever power sensors are configured, falling
  back to kWh × price when they are not.
- **Standby is counted.** The gap between one print ending and the next starting is
  measured too, and lands in `last_idle_cost`. On a printer drawing ~14 W at rest that is
  easily larger than the prints themselves.

Accrual is computed from elapsed time rather than tick count, so a missed or irregular
tick costs freshness, never accuracy.

## How a slot gets its price

In order of precedence:

1. The **tag library**, matched on the `tag_uid` the tray reports — the price of the spool
   actually loaded. A spool carries a tag on each side reporting different serials, so a
   row can name the other one in `serial_2`; either matches, so it prices the same
   whichever way round the spool goes in.
2. The slot's own **price number**, if you have set one.
3. The **default filament price**.

Each row in the breakdown carries `price_source` so you can see which applied.

### When a slot's price entity updates

The price numbers track what is loaded rather than being settings you maintain. They are
rewritten **the moment a tray changes** — the tray sensors are watched, so loading a spool
prices the slot from its tag immediately, and unloading one drops it to **0**. They are
also refreshed when a print **starts** and when it **finishes**, and on demand via
`bambu_costs.sync_slot_prices`.

A slot holding a spool the library does not know also goes to 0. Zero means "no price of
its own", so costing falls back to the default rather than charging nothing.

Two cases are deliberately skipped instead of zeroed, because neither means empty: a slot
with no tray sensor configured, and a tray whose own state is `unavailable` — usually the
printer being switched off, which must not look like every spool was unloaded.

None of this affects what a print costs. The tag price is resolved live at calculation
time, so the figures are right even if these entities are stale.

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

No automation is needed to snapshot the meters. The integration is already watching the
print-status transition, so it records both the energy total and the running cost total
when a print starts, and measures the job against them.

A resume is not a new job: coming back from a pause, or from a failure the printer
recovered out of, leaves both markers where they were. Re-marking would restart the meters
part-way through and undercount everything already spent.

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

## License

MIT — see [LICENSE](LICENSE).

The bundled brand sources keep their own terms: the euro glyph is public domain
(Openclipart), and the Bambu Lab mark is Bambu Lab's trademark, used to identify the
hardware this integration is for.
