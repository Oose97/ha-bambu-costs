# Cards

Registered automatically as Lovelace module resources, with the integration's version
and each file's own timestamp appended — so an upgrade, or even a hand-copied newer
file, busts the browser cache on its own. They show up under
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
- Editing a pair's filament, colour or price applies to both rows, and so does the
  **ON/OFF** toggle — a spool is one physical thing, retired whole. Serials stay
  per-row, since they are what tell the two tags apart. Typing a spool's second serial
  pairs the rows on the spot.
- The **Spool ID** column is the printer cloud's per-spool id, [learned by
  itself](filament.md#the-spool-id-learns-itself) whenever the spool is loaded — and
  the reason freshly scanned second sides pair up on their own. Editable like
  everything else; shared across a pair, one spool being one spool.
- The **Left** column is a ring showing how much of the spool remains — green, then
  yellow under 30%, orange under 20%, red under 10% — with the grams in its tooltip.
  Click it to type the grams directly; with a
  [filament inventory sensor](filament.md#remaining-grams-from-the-cloud-inventory)
  configured, the value keeps itself current. Shared across a pair, like everything
  else describing the spool.
- The colour-name cell is a combo over the whole Bambu palette: click it and the full
  list drops down, scrollable; start typing and it filters. The list is a convenience,
  not a constraint — anything you type is accepted as-is.

  ![The colour-name combo: the full palette on focus, filtering as you type](images/filament_color_drop_down.jpg)
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
- The footer counts rows and **spools** — a pair is one spool — with the active count
  beside it, tracking unsaved edits live. The saved figures are also published as the
  `spools` and `active_spools` [sensors](entities.md#sensors), ready for a badge or an
  automation.
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
configurable columns:

![The print history card: per-job costs, energy, materials, per-slot filament use — and a failed print's red-washed row with its layers reading finished/total](images/print_history_full_table.jpg)

The filter narrows it to anything — a date, a job name, a material:

![The print history filtered to one day](images/print_history_filtered_results.jpg)

Plain text matches anywhere in a row, exactly as it reads. Adding **`[AND]`**,
**`[OR]`** or **`[NOT]`** turns the box into a boolean expression, with parentheses
for grouping:

```
(2026-08-15 [OR] 2026-08-16) [AND] penguin
```

— the penguins printed on either of those two days. Operands sitting side by side are
AND-ed, so the `[AND]` above is optional; the operators are case-insensitive; and text
with no operator in it stays one literal phrase, so job names carrying their own
brackets or parentheses still search the way they look. A half-typed expression
matches on the words it already has rather than emptying the table, and the footer
says so.

- Every value field edits in place — click a cell, type, and press **Save**. Nozzle
  size and type are combo fields: free text, with the printer's own vocabulary offered
  as a dropdown (labels prettified, the printer's spelling stored). **Discard** appears
  beside Save while there are unsaved edits.

  ![Editing a row: the nozzle type dropdown open, one unsaved edit, Discard and Save waiting](images/print_history_unsaved_changes.jpg) Only the
  rows you touched are written, matched into the file by the timestamp they were loaded
  with, so jobs logged while you were editing are never overwritten. The previous file
  is kept as `jobs.csv.bak`.
- Every row carries a **🗑** button. A deletion is staged like any other edit — the row
  is struck through, the button flips to ↩ to take it back, and only **Save** actually
  removes it from the file (with the previous version in `jobs.csv.bak` as the net).
- **+ Print** in the toolbar expands to the two manual forms:

  ![+ Print expands to Add finished print and Add failed print](images/print_history_add_print.jpg)

  ***Add failed print*** logs a print that died part-way. The form is
  pre-filled by the integration — from the print running now, or the last one once the
  printer is idle — with one extra field: **how many layers finished**. The filament
  figures start as the job's plan scaled by that ratio (the printer only ever reports
  planned weights), and editing the layer count rescales them; duration, energy and
  electricity are the stint's measured reality and are not scaled — for a print still
  running, the Print time field notes the planned duration alongside, the way the
  layers pair reads done against total. Everything is editable, per AMS slot included,
  and the job name arrives prefixed with `[FAILED]` so the log reads at a glance —
  edit the tag away in the form if you'd rather not have it.

  ![The failed-print form: layers completed over total, the plan scaled to match, everything editable](images/print_history_add_failed_print_modal.jpg)

  The picture is a deliberate choice: press **📷 Capture photo** for a camera shot of
  the failed plate, or Save stores the slicer's render. A checkbox (on by default)
  banks the row's filament — the scaled figures, not the full plan — to the lifetime
  totals on save.

  ![The Picture row before capturing: one button, and Save would keep the render](images/print_history_add_print_capture_before_click.jpg)
  ![After capturing: the camera's shot of the plate, with a retake one click away](images/print_history_add_print_capture_after_click.jpg)

- ***Add finished print*** is its twin, for a completed job the integration never saw
  finish — Home Assistant down at the moment the printer reported it, or a job worth
  logging after the fact. Same pre-filled form, minus the layer scaling: the plan
  stands as reported, a single Layers field, and the same capture button and totals
  checkbox.

  ![The finished-print form: the plan as reported, no scaling, ready to save](images/print_history_add_finished_print.jpg)
- A failed print's row wears the faintest red wash, and its **Layers** cell shows
  `finished/total` — both halves editable. **Hide failed prints** in the settings is on
  by default; the footer counts what is hidden.
- A **totals row** sits under the table, summing every numeric column on screen —
  print time, weight, length, energy and the three costs — over **everything the
  filter kept**, not just the page in view. It pins itself to the bottom of the box
  the way the header pins to the top, and switches off in the settings.
- **⚙** opens the table settings: column order and visibility, the default sort column
  and direction, the rows per page, the table height, and whether failed prints and
  the totals row are shown — all remembered per browser. Display only; a save always
  writes every field.

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

  A multi-material job carries the full product name per slot, while the Material
  column above shows the shortened pair (`PLA Basic, PETG HF`):

  ![The per-slot breakdown of a multi-material job — PLA and PETG in one print](images/print_history_filament_used_multimaterial.jpg)

```yaml
type: custom:bambu-costs-jobs-table
entity: sensor.bambu_costs_job_log
page_size: 20
```

`page_size` is the default page length for browsers that have not chosen their own in
the settings.

## Printing now

`custom:bambu-costs-printing-now` — the job on the printer, as the row it will be
logged as, editable while it prints.

![The Printing-now card: the render beside the live figures, a renamed job wearing its edit mark, the predicted total, and the per-slot filament table](images/printing_now_card.jpg)

- **What you edit here is what the finished job logs.** Only the fields you touch are
  stored (marked with an accent bar); everything untouched keeps following live data,
  and a **↺ Reset edits** button drops the lot. Edits survive a restart mid-print, are
  kept through a pause or jam recovery, and are cleared when a new job starts. If the
  print dies instead of finishing, the failed-print form opens with these edits
  already applied.
- Editable: the job name, layers, weight, length, nozzle size and type, material,
  filament cost, and every per-slot line — with the same maths as everywhere else:
  weight or price moves a line's cost, the lines roll up into the row's weight and
  filament cost, and any computed value can still be overwritten directly.
- Read-only, because they are measured at the finish rather than decided in advance:
  elapsed time (with the planned duration alongside while it runs), the current
  layer, energy, electricity so far, and the running total. The date stays the
  moment the job finishes, as always.
- A **predicted total** sits beside them: the filament (as edited) plus projected
  electricity. Past 5% of the planned duration the projection is the print's own rate
  — spent so far over fraction done; before that, when the sample is mostly heat-up,
  the last logged print's measured rate stands in. It never predicts below what the
  meter already shows.
- The slicer's render of the job shows beside the name — click it for a bigger look.
- One caveat: a price edited here changes the **logged row only**. The live session
  sensors keep following the slot price numbers — the [SET picker](#tags-editor) is
  the tool when the slot itself has the wrong price.
- When the printer is idle the card just says so; history is the
  [jobs table](#jobs-table)'s business.

```yaml
type: custom:bambu-costs-printing-now
entity: sensor.bambu_costs_current_job
```

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
