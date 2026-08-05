# Brand assets

`icon.svg` is the source of truth. `icon.png` (256×256) and `icon@2x.png` (512×512)
are generated from it by `make_icon.py`, transparent and trimmed to centred artwork —
the shape [home-assistant/brands](https://github.com/home-assistant/brands) expects.

Regenerate with:

```bash
python make_icon.py .
```

Neither mark is redrawn. `sources/bambu-lab-logo.svg` supplies the logo geometry — the
first four subpaths of `path4491`, which are pure straight lines — and
`sources/euro-sign.svg` supplies the euro, an official-guidelines glyph published to the
public domain by rickvanderzwet via Openclipart. The euro carries bezier curves, so the
PNG uses a flattened copy while the SVG keeps the original path under the same transform;
both are driven by one set of numbers so they cannot drift apart.

Colours are Bambu green `#00AE42` and official EU blue `#003399`. The slashes through the
mark are transparent rather than white, so the icon sits on any background.

## Where they are used

Since Home Assistant 2026.3 a custom integration ships its own brand images: the two PNGs
are copied to `custom_components/bambu_costs/brand/`, which Home Assistant serves from
`/api/brands/integration/bambu_costs/icon.png`. Local images take priority over the brands
CDN, so no pull request to `home-assistant/brands` is needed — that repository no longer
accepts custom integrations anyway.

Copies live in both places on purpose: this folder holds the generator and its sources,
which have no business being downloaded onto every install, while the integration folder
carries only the two PNGs it actually serves. Re-run `make_icon.py` here, then copy
`icon.png` and `icon@2x.png` across.

The Bambu Lab mark is Bambu Lab's trademark; it is used here to identify which hardware
this integration is for, which is the usual practice for Home Assistant integration icons.
