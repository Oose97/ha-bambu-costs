# Data on disk

## Files on disk

```
config/bambu_costs/<entry_id>/tags.csv
config/bambu_costs/<entry_id>/tags.csv.bak
config/bambu_costs/<entry_id>/jobs.csv
config/bambu_costs/<entry_id>/jobs.csv.bak
config/bambu_costs/<entry_id>/covers/*.jpg
```

Both CSVs have a header row and are written with a real CSV writer, so commas and quotes
inside a value are quoted rather than stripped. A headerless file still loads, so you can
drop an existing tag list in unchanged. The `.bak` next to each file is the previous
version, written before any whole-file save — a tag-library save, or edits from the jobs
table. When a new column is added in an upgrade, the jobs file is brought up to the
current header on the first write after it.

Covers are served at `/bambu-costs-covers/`. Nothing else under `config/` is exposed.

The bulky `data` and `slots` attributes are excluded from the recorder automatically —
no hand-written `recorder:` exclusion needed.
