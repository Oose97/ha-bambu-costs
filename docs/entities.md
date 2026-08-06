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
| `sensor.<name>_tag_library` | Your filament tag library. State is the row count; `data` holds the rows. |
| `sensor.<name>_cost_rate` | What the machine is costing per hour right now — power × price. |
| `sensor.<name>_cost_total` | **Electricity only.** Everything it has cost to run, printing or idle. Restored across restarts. |
| `sensor.<name>_total_spend` | **The whole bill** — filament, electricity and standby. Metering source; see [Costs per month](costing.md#costs-per-month). |
| `sensor.<name>_job_log` | Logged jobs. State is the row count; `data` holds the rows. |

## Numbers

Plain writable numbers. Set them by hand in the UI or from an automation with
`number.set_value`. Values survive restarts.

- `number.<name>_default_filament_price` — fallback price per kg
- `number.<name>_<slot>_filament_price` — one per configured slot
- `number.<name>_electricity_price` — per kWh, the fallback when no price sensor is set
- `number.<name>_last_print_cost`, `_last_print_filament_cost`, `_last_print_power_cost`
- `number.<name>_total_filament_used`, `_total_cost` — lifetime running totals
- `number.<name>_energy_at_print_start` — snapshot taken when a print begins
- `number.<name>_cost_at_print_start`, `_cost_at_print_end` — markers in the running total
- `number.<name>_last_idle_cost` — electricity burnt between the last two prints

## Buttons

- `button.<name>_charge_filament_to_totals` — adds the current job's filament cost and
  weight to the lifetime totals. For a print that failed part-way. Deliberately manual:
  the printer reports the job's *planned* weight, so charging a failure automatically
  would bill a first-layer failure in full. The last press is recorded in the button's
  attributes so a mis-press is visible.

## Switches

- `switch.<name>_use_camera_snapshot` — created when a printer camera is configured.
  While on, each logged job's picture is a camera frame grabbed the moment the printer
  reports finish — the part still on the plate — instead of the slicer's render. If the
  frame grab fails, the render is captured instead, so the job still gets a picture.
  A switch rather than an option because it is worth flipping per job.

## Services

| Service | Does |
| --- | --- |
| `bambu_costs.log_job` | Appends the finished job, captures the cover image, advances the totals. Anything you do not pass is read from the configured sensors. |
| `bambu_costs.write_tags` | Replaces the tag library. Previous file kept as `tags.csv.bak`. |
| `bambu_costs.set_tag_price` | Updates the price on every tag with a given RFID serial. |
| `bambu_costs.refresh` | Re-reads the CSVs from disk. |
| `bambu_costs.sync_slot_prices` | Copies the loaded spool's tag price into each slot's price number. |

Pass `entry_id` only if you have set up more than one printer.

### Job pictures

Job pictures come from the **cover image** entity (the slicer's render) or, with the
camera switch on, from the **printer camera** — a photo of what actually came off the
plate, since the job is logged the moment the printer reports finish, while the part is
still on it. Either way the picture is thumbnailed to 320 px before storage, so a camera
frame costs tens of kilobytes per job, not a full-resolution snapshot. Old rows keep
whatever was captured at the time.

### Logging a finished job

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
