# Setup

## Requirements

Home Assistant 2024.12 or newer, and a source of printer sensors — in practice the
[ha-bambulab](https://github.com/greghesp/ha-bambulab) integration, which is what this was
built against and what the setup screen expects to find.

That dependency is declared as `after_dependencies`, not `dependencies`: if `bambu_lab` is
installed it loads first so its sensors exist before the first refresh, but this
integration will still set up without it. All data comes in through the entities you pick
during setup rather than through ha-bambulab's internals, so a fork — or an entirely
different printer integration — works too, as long as it exposes a per-slot print weight
sensor.

## The setup flow

**Step 1 — pick the printer device.** The list is narrowed to the printer's brand, and
picking an accessory works too: AMS units hang off the printer via `via_device`, and
discovery walks that chain to its root. Everything else is filled in from the device: the
sensors, and any AMS slots the printer is currently reporting, each paired with its tray.
Leave it empty to configure by hand.

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
This is also where the optional **printer camera** goes — see
[Job pictures](entities.md#job-pictures).

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

## Icon

Shipped with the integration in `custom_components/bambu_costs/brand/`, so it shows in
Settings → Devices & Services with no brands-repository submission. Requires Home
Assistant 2026.3 or newer; on older versions the default placeholder is used instead.
