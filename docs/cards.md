# Cards

Registered automatically as Lovelace module resources, with the integration's version
appended so an upgrade busts the browser cache on its own. They show up under
Settings → Dashboards → Resources, and are removed when the last config entry is
deleted. In YAML-mode Lovelace the files are still served — the URLs are logged at
startup for you to add by hand.

## Tags editor

`custom:bambu-costs-tags-editor` — editable, reorderable filament tag library.

- A spool's two tags render as one row, the second tag a child row behind a **▸** on the
  spool's handle — collapsed by default, with the default changeable in settings.
- Editing a pair's filament, colour or price applies to both rows; serials stay per-row,
  since they are what tell the two tags apart. Typing a spool's second serial pairs the
  rows on the spot.
- Pairs share one handle and move as a unit, and reordering works with rows hidden — it
  steps over what is not shown. Filtering finds collapsed second tags and surfaces them
  with their spool.
- **⚙** opens the table settings: show-disabled, expand-by-default, sorting, the table
  height, and the column layout (display only — a save always writes every field in
  canonical order).
- By default the table is bounded to 70% of the screen and scrolls inside its own box,
  which keeps the header row pinned while a long library scrolls under it. "Unlimited"
  in the settings grows the card with the page instead.
- Each row's **SET** button opens a picker listing every filament price entity — the
  default first, then one per configured slot — so a tag's price can be pushed into
  whichever slot has that spool loaded. The list is resolved from the entity registry,
  so it follows the slot configuration on its own.

```yaml
type: custom:bambu-costs-tags-editor
entity: sensor.bambu_costs_tag_library
```

## Jobs table

`custom:bambu-costs-jobs-table` — editable print history: sortable, paginated, with
configurable columns.

- Every value field edits in place — click a cell, type, and press **Save**. Nozzle
  size and type are dropdowns of what the printer can report (labels prettified, the
  printer's own spelling stored), with **Other…** switching to free text. Only the
  rows you touched are written, matched into the file by the timestamp they were loaded
  with, so jobs logged while you were editing are never overwritten. The previous file
  is kept as `jobs.csv.bak`.
- **⚙** opens the table settings: column order and visibility, the default sort column
  and direction, the rows per page, and the table height — all remembered per browser.
  Display only; a save always writes every field.
- By default the table is bounded to 70% of the screen and scrolls inside its own box:
  the header row stays pinned while long pages scroll under it, and the horizontal
  scrollbar sits at the bottom of the box instead of below the last row. "Unlimited"
  grows the card with the page instead.
- The **Material** column lists each distinct filament type once, brand prefix dropped —
  `PLA Basic` for a single-material job, `PLA Basic, PETG HF` for a multi-material one.
  Filled in automatically when a job is logged; free text when editing.
- The image cell is a **View** button opening the job's cover in a modal.

```yaml
type: custom:bambu-costs-jobs-table
entity: sensor.bambu_costs_job_log
page_size: 20
```

`page_size` is the default page length for browsers that have not chosen their own in
the settings.

## Cost calculator

`custom:bambu-costs-calculator` — manual quote: filament, runtime, margin, VAT. Paired
tags collapse to one dropdown entry, and an **Other** option takes a hand-typed price.

```yaml
type: custom:bambu-costs-calculator
entity: sensor.bambu_costs_tag_library
rate_per_minute: 0.0008
margin_percent: 30
vat_percent: 21
```
