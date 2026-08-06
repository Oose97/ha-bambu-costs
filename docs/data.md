# Data on disk

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
