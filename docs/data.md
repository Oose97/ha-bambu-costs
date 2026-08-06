# Data on disk, importing, and migrating

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
on serial — either of a spool's two serials counts — so nothing duplicates. Pass
`replace: true` to wipe first instead of merging.

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
