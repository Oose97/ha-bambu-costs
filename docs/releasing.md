# Releasing

`main` is protected: changes land through a pull request that passes Validate.

Releases are cut automatically. Bump `version` in
`custom_components/bambu_costs/manifest.json` as part of the change; once it merges and
Validate passes on `main`, the Release workflow tags `vX.Y.Z` and publishes it with
generated notes. A merge that does not change the version publishes nothing, so
documentation-only changes do not churn out releases.

The manifest is the single source of truth — it is what Home Assistant and HACS actually
read, and the tag follows it rather than the other way round.
