# Cards

Registered automatically as Lovelace module resources, with the integration's version
appended so an upgrade busts the browser cache on its own. They show up under
Settings → Dashboards → Resources, and are removed when the last config entry is
deleted. In YAML-mode Lovelace the files are still served — the URLs are logged at
startup for you to add by hand.

## Tags editor

`custom:bambu-costs-tags-editor` — editable, reorderable filament tag library.

![The filament tag library: colour swatches, names with Bambu codes, both RFID serials and the price per spool](images/filaments_full_table.jpg)

- A spool's two tags render as one row, the second tag a child row behind a **▸** on the
  spool's handle — collapsed by default, with the default changeable in settings.

  ![A paired spool collapsed to one row](images/filaments_group_collapsed.jpg)
  ![The same spool expanded, its second tag as a child row](images/filaments_group_expanded.jpg)
- Editing a pair's filament, colour or price applies to both rows; serials stay per-row,
  since they are what tell the two tags apart. Typing a spool's second serial pairs the
  rows on the spot.
- The colour-name cell is a combo over the whole Bambu palette: click it and the full
  list drops down, scrollable; start typing and it filters. The list is a convenience,
  not a constraint — anything you type is accepted as-is.
- Pairs share one handle and move as a unit, and reordering works with rows hidden — it
  steps over what is not shown. Filtering finds collapsed second tags and surfaces them
  with their spool.
- **⚙** opens the table settings: show-disabled, expand-by-default, sorting, the table
  height, and the column layout (display only — a save always writes every field in
  canonical order).

  ![The tags editor's settings sheet](images/filaments_table_settings.jpg)
- By default the table is bounded to 70% of the screen and scrolls inside its own box,
  which keeps the header row pinned while a long library scrolls under it. "Unlimited"
  in the settings grows the card with the page instead.
- Each row's **SET** button opens a picker listing every filament price entity — the
  default first, then one per configured slot — so a tag's price can be pushed into
  whichever slot has that spool loaded. The list is resolved from the entity registry,
  so it follows the slot configuration on its own.

  ![The SET picker: every price target with its current value](images/filament_set_price_modal.jpg)

- Works on a phone and follows the theme — on touch, reordering switches to ↑/↓
  buttons on its own:

  ![The tag library on a phone, dark theme, arrow reordering](images/filaments_mobile_dark_mode.jpg)

```yaml
type: custom:bambu-costs-tags-editor
entity: sensor.bambu_costs_tag_library
```

## Jobs table

`custom:bambu-costs-jobs-table` — editable print history: sortable, paginated, with
configurable columns. Pictured at the top of the [README](../README.md); the filter
narrows it to anything — a date, a job name, a material:

![The print history filtered to one day](images/print_history_filtered_results.jpg)

- Every value field edits in place — click a cell, type, and press **Save**. Nozzle
  size and type are combo fields: free text, with the printer's own vocabulary offered
  as a dropdown (labels prettified, the printer's spelling stored). **Discard** appears
  beside Save while there are unsaved edits.

  ![Editing a row: the nozzle type dropdown open, one unsaved edit, Discard and Save waiting](images/print_history_unsaved_changes.jpg) Only the
  rows you touched are written, matched into the file by the timestamp they were loaded
  with, so jobs logged while you were editing are never overwritten. The previous file
  is kept as `jobs.csv.bak`.
- **⚙** opens the table settings: column order and visibility, the default sort column
  and direction, the rows per page, and the table height — all remembered per browser.
  Display only; a save always writes every field.

  ![The jobs table's settings sheet](images/print_history_table_settings.jpg)
- By default the table is bounded to 70% of the screen and scrolls inside its own box:
  the header row stays pinned while long pages scroll under it, and the horizontal
  scrollbar sits at the bottom of the box instead of below the last row. "Unlimited"
  grows the card with the page instead.
- The **Material** column lists each distinct filament type once. For display it is
  shortened to just the type whatever the brand — a stored `SUNLU PETG` reads `PETG`,
  `Bambu PLA Matte` reads `PLA Matte` — matched against a list of known type names
  (the Bambu lineup by default, editable in the integration's options); the tooltip
  keeps the full stored value, which never changes.
- The image cell is a **View** button opening the job's cover in a modal — with the
  camera switch on, that's a photo of what actually came off the plate:

  ![A job's cover image: the camera's photo of the finished plate](images/print_history_image_view.jpg)

- **Filament used** is a compact per-row summary; clicking it opens the per-slot
  breakdown, where every field — label, material, colour, name, weight, price, cost —
  edits in place, cost following weight and price the way the logger computed it.

  ![The per-slot breakdown of a three-colour job](images/print_history_filament_used_multicolor_same_material.jpg)

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

![A quote combining a library spool and a hand-priced one](images/print_cost_calculator_card.jpg)

```yaml
type: custom:bambu-costs-calculator
entity: sensor.bambu_costs_tag_library
rate_per_minute: 0.0008
margin_percent: 30
vat_percent: 21
```
