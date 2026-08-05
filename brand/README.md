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

## Getting it to show in Home Assistant

A custom integration cannot set its own icon from its own repository — Home Assistant
reads icons from the brands repository. To have it appear under Settings → Devices &
Services, submit `icon.png` and `icon@2x.png` there under
`custom_integrations/bambu_costs/`. Until then these are the repository and HACS listing
images.

The Bambu Lab mark is Bambu Lab's trademark; it is used here to identify which hardware
this integration is for, which is the usual practice for Home Assistant integration icons.
