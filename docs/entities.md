# Entities and services

Everything the integration creates for one config entry. `<name>` is the entry's
slug — `bambu_costs` by default. If the device is assigned to an area, entities
created *after* the assignment carry the area slug as a prefix, so both
`sensor.bambu_costs_total_spend` and `sensor.living_room_bambu_costs_total_spend`
are possible shapes in one install.

## Sensors

| Entity | What it holds |
| --- | --- |
| `sensor.<name>_filament_breakdown` | Cost of the job on the printer now. The `slots` attribute has the unrounded per-slot rows. |
| `sensor.<name>_session_filament_cost` | The same figure rounded for display. |
| `sensor.<name>_session_power_cost` | What the print on the printer has cost in electricity so far — live while it runs, the finished print's figure until the next one starts. |
| `sensor.<name>_tag_library` | Your filament tag library. State is the row count; `data` holds the rows. |
| `sensor.<name>_spools` | Distinct spools in the library — a paired spool's two rows count as one, however the pairing is recorded. |
| `sensor.<name>_active_spools` | The same count without the disabled spools. A pair with one side still enabled counts as active. |
| `sensor.<name>_cost_rate` | What the machine is costing per hour right now — power × price. |
| `sensor.<name>_cost_total` | **Electricity only.** Everything it has cost to run, printing or idle. Restored across restarts. |
| `sensor.<name>_total_spend` | **The whole bill** — filament, electricity and standby. Metering source; see [Costs per month](costing.md#costs-per-month). |
| `sensor.<name>_job_log` | Logged jobs. State is the row count; `data` holds the rows. |
| `sensor.<name>_current_job` | The job on the printer now — `printing`/`idle`. `row` is the live draft with the Printing-now card's edits applied; `edited` names the touched fields. |

## Numbers

Plain writable numbers. Set them by hand in the UI or from an automation with
`number.set_value`. Values survive restarts.

- `number.<name>_default_filament_price` — fallback price per kg
- `number.<name>_<slot>_filament_price` — one per configured slot
- `number.<name>_electricity_price` — per kWh, the fallback when no price sensor is set
- `number.<name>_last_print_cost`, `_last_print_filament_cost`, `_last_print_power_cost`
- `number.<name>_total_filament_used`, `_total_cost` — lifetime running totals
- `number.<name>_energy_at_print_start`, `_energy_at_print_end` — snapshots taken as a
  print begins and ends, aborts included — they are what lets a failed print logged
  later carry the job's own energy, without the standby since
- `number.<name>_cost_at_print_start`, `_cost_at_print_end` — markers in the running total
- `number.<name>_cost_at_idle_start` — where the current idle window began; moves only
  when a print really ends, so a restart mid-idle cannot truncate the idle figure
- `number.<name>_last_idle_cost` — electricity burnt between the last two prints

## Switches

- `switch.<name>_maintenance_mode` — while on, a logged job is electricity only:
  the name reads **Maintenance**, the duration, energy and power cost are recorded,
  and nothing else — no filament figures, no per-slot rows, no picture. For
  calibration lines, flow tests and cleaning runs whose filament is not worth
  billing to any spool. Everything live (slot prices, tag scanning, the session
  sensors) keeps working; only what reaches the log changes. Outranks the
  Printing-now card's edits and `log_job` overrides alike.
- `switch.<name>_use_camera_snapshot` — created when a printer camera is configured.
  While on, each logged job's picture is a camera frame grabbed the moment the printer
  reports finish — the part still on the plate — instead of the slicer's render. If the
  frame grab fails, the render is captured instead, so the job still gets a picture.
  A switch rather than an option because it is worth flipping per job.
- `switch.<name>_always_take_remaining_on_load` — created when a filament inventory
  sensor is configured. While on, loading a spool writes the tray's own remaining %
  (as grams of an assumed 1 kg spool) to the library right away, and the next
  inventory reading overwrites it — the cloud stays the source of truth. Without an
  inventory sensor there is no switch: the on-load figure is taken unconditionally,
  being the only one there is. See
  [the tray's own figure, on load](filament.md#the-trays-own-figure-on-load).

## Services

| Service | Does |
| --- | --- |
| `bambu_costs.log_job` | Appends the finished job, captures the cover image, advances the totals. Anything you do not pass is read from the configured sensors. |
| `bambu_costs.add_job` | Appends one fully explicit row — the save path of both manual forms. Reads no live state, so it can never swallow a running job's own auto-log. `update_totals` banks the row's filament. |
| `bambu_costs.draft_job` | Returns a pre-filled row for logging a print by hand — the current print, or the last one once the printer is idle. Backs the failed-print and finished-print forms. Read-only. |
| `bambu_costs.capture_cover` | Takes a camera photo now and stores it as a job cover; returns the filename and URL. The failed-print form's capture button. |
| `bambu_costs.update_current_job` | Stores edits for the job printing now — only the touched fields, applied when the job is logged, cleared when a new one starts. `clear: true` drops them. The Printing-now card's save path. |
| `bambu_costs.write_jobs` | Applies edited log rows, matched into the file by the timestamp they were loaded with; a row carrying `delete: true` is removed instead. Previous file kept as `jobs.csv.bak`. |
| `bambu_costs.write_tags` | Replaces the tag library. Previous file kept as `tags.csv.bak`. |
| `bambu_costs.set_tag_price` | Updates the price on every tag with a given RFID serial. |
| `bambu_costs.refresh` | Re-reads the CSVs from disk. |
| `bambu_costs.sync_slot_prices` | Copies the loaded spool's tag price into each slot's price number. |

Pass `entry_id` only if you have set up more than one printer — and even then only
when calling by hand: the cards pass it by themselves, from the `entry_id` attribute
their sensor publishes, so several entries can be loaded side by side.

### Job pictures

Job pictures come from the **cover image** entity (the slicer's render) or, with the
camera switch on, from the **printer camera** — a photo of what actually came off the
plate, since the job is logged the moment the printer reports finish, while the part is
still on it. Either way the picture is thumbnailed to 320 px before storage, so a camera
frame costs tens of kilobytes per job, not a full-resolution snapshot. Old rows keep
whatever was captured at the time.

### Logging a finished job

No automation is needed. The integration watches the print-status transition itself: it
snapshots the meters when a print starts, measures the duration off the same transitions,
and **appends the job to the log when the printer reports finish** — cover picture,
totals and all. The *Log finished jobs automatically* option (on by default) controls
this.

Aborted prints are deliberately not logged automatically — the printer reports a job's
*planned* weight, so logging a failure blind would bill a first-layer crash in full.
Their electricity still reaches the total either way (see [costing](costing.md)). The
judgement call — how far did it actually get — is the jobs card's
[failed-print form](cards.md#jobs-table): pre-filled from the printer, scaled by the
layers that finished, the job name marked `[FAILED]` (edit it away if unwanted), and
able to bank the scaled filament to the totals as it saves.
Its twin, the finished-print form, covers the opposite gap — a completed job the
integration never saw finish (Home Assistant down at the time, say) — with the same
pre-fill and the same totals checkbox.

The `bambu_costs.log_job` service stays for passing overrides — a corrected duration, an
explicit cost. A call for a job that is already logged is skipped, so a service call on
the same finish transition cannot write a second row; pass `force: true` to deliberately
re-log with corrected values.

A resume is not a new job: coming back from a pause, or from a failure the printer
recovered out of, leaves the meters and the duration where they were. The job's length is
measured live; the printer's own start/end time sensors are only a fallback for a job
whose start Home Assistant never saw.
