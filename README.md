# Bambu Print Costs

<img src="brand/icon.svg" width="96" alt="">

A Home Assistant integration that works out what a 3D print actually cost — filament per
AMS slot, electricity, and a per-job history — and ships the Lovelace cards to manage it.

It replaces a pile of `command_line` sensors, `shell_command` entries, shell scripts,
`input_number` helpers and manually-registered card resources with one config entry.

**Nothing is hard-coded.** Every sensor it reads is chosen during setup, and the filament
slots are free-form, so any AMS layout — or none — works.

## Highlights

- **Per-slot filament costing** from your own tag library, priced by the RFID tag of the
  spool actually loaded — a spool's two tags count as one spool.
- **Electricity integrated, not estimated**: a variable tariff is charged as it moved
  during the print, standby between prints is counted, and even an aborted print's
  power reaches the total. Cross-checked against the energy counters, so a smart plug
  dropping off the network cannot silently under-bill a job.
- **A job log with pictures** — the slicer's render, or a camera photo of what actually
  came off the plate.
- **Spools scan themselves in**: loading an unknown tag appends a library row, named
  from Bambu's colour palette, ready for you to price.
- **Three cards** — tag library editor, print history, quote calculator — registered
  automatically, no resource wrangling.
- Survives restarts, reconnects and mid-print dropouts without losing or double-counting
  a cent.

## Install

**HACS** → three-dot menu → *Custom repositories* → add this repo as an **Integration**,
then download it and restart Home Assistant.

**Manually**: copy `custom_components/bambu_costs` into your `config/custom_components/`
and restart.

Then *Settings → Devices & Services → Add Integration → Bambu Print Costs*. Pick your
printer and the sensors are filled in for you — see [Setup](docs/setup.md).

Requires Home Assistant 2024.12+ and a printer integration exposing per-slot print
weights — in practice [ha-bambulab](https://github.com/greghesp/ha-bambulab), though
nothing is read from it directly.

## Quick start

Add the cards to a dashboard:

```yaml
type: custom:bambu-costs-tags-editor
entity: sensor.bambu_costs_tag_library
```

Log each finished job from an automation:

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

Everything else — meter snapshots, slot prices, idle tracking — happens on its own.

## Documentation

| | |
| --- | --- |
| [Setup](docs/setup.md) | The config flow, device discovery, slot syntax, currency, icon. |
| [Entities & services](docs/entities.md) | Every sensor, number, button, switch and service, plus the job-logging automation. |
| [Electricity costing](docs/costing.md) | Variable tariffs, integration vs estimation, outage handling, monthly costs via `utility_meter`. |
| [Filament pricing](docs/filament.md) | How a slot gets its price, tag scanning, spool pairs, restart survival. |
| [Cards](docs/cards.md) | The three cards and their options. |
| [Data on disk](docs/data.md) | Where the CSVs and cover images live, and how they are written. |
| [Releasing](docs/releasing.md) | How versions and releases are cut. |

## Not included yet

- No dashboard is created for you; the cards are yours to place.
- Pricing fallbacks by material or colour when a spool carries no known tag; every
  unknown spool falls back to the one default price.

## License

MIT — see [LICENSE](LICENSE).

The bundled brand sources keep their own terms: the euro glyph is public domain
(Openclipart), and the Bambu Lab mark is Bambu Lab's trademark, used to identify the
hardware this integration is for.
