"""Bambu filament colour names, keyed by material, product line and hex.

The printer reports a colour but not what Bambu calls it, so a scanned spool
would otherwise land in the library as a bare hex code. The numbers in
parentheses are Bambu's own filament codes — and they are per product line:
#FFFFFF is "Jade White (10100)" as PLA Basic, "Ivory White (11100)" as PLA
Matte and "Pure White (17100)" as PLA Pure, which is why the map is keyed by
material and then line.

A multi-colour filament reports a different hex depending which part of the
gradient the tag was read from; every one of its hexes maps to its name.

Unknown hexes are not an error — a third-party spool is simply named by the
colour-name lookup, or keeps the placeholder until someone edits the row.
"""

from __future__ import annotations

import re

UNKNOWN_COLOR = "Unknown Color"

# Checked in this order when the caller does not know the material.
MATERIAL_PREFERENCE = ("PLA", "PETG", "TPU", "ABS", "ASA", "PC", "PA6", "PAHT", "PET", "PPA", "PPS", "PVA", "HIPS")

COLOR_NAMES_BY_LINE: dict[str, dict[str, dict[str, str]]] = {
    "PLA": {
        "Basic": {
            "#000000": 'Black (10101)',
            "#002914": 'Green (10500)',
            "#0056B8": 'Cobalt Blue (10604)',
            "#0086D6": 'Cyan (10603)',
            "#00AE42": 'Bambu Green (10501)',
            "#00B1B7": 'Turquoise (10605)',
            "#0A2989": 'Blue (10600)',
            "#3F8E43": 'Mistletoe Green (10502)',
            "#482960": 'Indigo Purple (10701)',
            "#545454": 'Dark Gray (10105)',
            "#5D6578": 'Blue Gray (10602)',
            "#5E43B7": 'Purple (10700)',
            "#6F5034": 'Cocoa Brown (10802)',
            "#847D48": 'Bronze (10801)',
            "#8E9089": 'Gray (10103)',
            "#9D2235": 'Maroon Red (10205)',
            "#9D432C": 'Brown (10800)',
            "#A6A9AA": 'Silver (10102)',
            "#BECF00": 'Bright Green (10503)',
            "#D1D3D5": 'Light Gray (10104)',
            "#E4BD68": 'Gold (10401)',
            "#EC008C": 'Magenta (10202)',
            "#F4EE2A": 'Yellow (10400)',
            "#F5547C": 'Hot Pink (10204)',
            "#F55A74": 'Pink (10203)',
            "#F7E6DE": 'Beige (10201)',
            "#FEC600": 'Sunflower Yellow (10402)',
            "#FF0000": 'Red (10200)',
            "#FF6A13": 'Orange (10300)',
            "#FF9016": 'Pumpkin Orange (10301)',
            "#FFFFFF": 'Jade White (10100)',
        },
        "Aero": {
            "#000000": 'Black (14103)',
            "#CDCECA": 'Gray (14104)',
            "#FFFFFF": 'White (14102)',
        },
        "CF": {
            "#000000": 'Black (14100)',
            "#2842AD": 'Royal Blue (14601)',
            "#4D5054": 'Lava Gray (14101)',
            "#5C9748": 'Matcha Green (14500)',
            "#69398E": 'Iris Purple (14700)',
            "#6E88BC": 'Jeans Blue (14600)',
            "#951E23": 'Burgundy Red (14200)',
        },
        "CMYK": {
            "#00FFFF": 'Lithophane Bundle',
            "#FF00FF": 'Lithophane Bundle',
            "#FFFF00": 'Lithophane Bundle',
            "#FFFFFF": 'Lithophane Bundle',
        },
        "Galaxy": {
            "#3B665E": 'Green (13503)',
            "#424379": 'Nebula (13504)',
            "#594177": 'Purple (13602)',
            "#684A43": 'Brown (13203)',
        },
        "Glow": {
            "#7AC0E9": 'Glow Blue (15600)',
            "#A1FFAC": 'Glow Green (15500)',
            "#F17B8F": 'Glow Pink (15200)',
            "#F8FF80": 'Glow Yellow (15400)',
            "#FF9D5B": 'Glow Orange (15300)',
        },
        "Gradient": {
            "#307FE2": 'Ocean to Meadow (10902)',
            "#4EC83A": 'Mint Lime (10904)',
            "#54FF9B": 'Ocean to Meadow (10902)',
            "#6FCAEF": 'Blueberry Bubblegum (10905)',
            "#8573DD": 'Blueberry Bubblegum (10905)',
            "#8EC9E9": 'Cotton Candy Cloud (10907)',
            "#9CDBD9": 'Arctic Whisper (10900)',
            "#D7FE9E": 'Mint Lime (10904)',
            "#E4555E": 'Pink Citrus (10903)',
            "#E7C1D5": 'Cotton Candy Cloud (10907)',
            "#ED6022": 'Dusk Glare (10906)',
            "#FC776A": 'Solar Breeze (10901)',
            "#FCDAD2": 'Pink Citrus (10903)',
            "#FFCBA6": 'Dusk Glare (10906)',
            "#FFF7F5": 'Solar Breeze (10901)',
            "#FFFFFF": 'Arctic Whisper (10900)',
        },
        "Lite": {
            "#000000": 'Black (16100)',
            "#004EA8": 'Blue (16601)',
            "#00BB31": 'Green (16501)',
            "#00FFFF": 'Cyan (16600)',
            "#6F6E6D": 'Dark Gray (16102)',
            "#8E3C06": 'Cocoa Brown',
            "#9FA19F": 'Gray (16101)',
            "#F7E6DE": 'Beige (16700)',
            "#FF0000": 'Red (16200)',
            "#FF671F": 'Orange (16301)',
            "#FFB549": 'Sunflower Yellow (16401)',
            "#FFD834": 'Yellow (16400)',
            "#FFFEF7": 'White (16103)',
        },
        "Marble": {
            "#AD4E38": 'Red Granite (13201)',
            "#F7F3F0": 'White Marble (13103)',
        },
        "Matte": {
            "#000000": 'Charcoal (11101)',
            "#0078BF": 'Marine Blue (11600)',
            "#042F56": 'Dark Blue (11602)',
            "#4D3324": 'Dark Chocolate (11802)',
            "#56B7E6": 'Sky Blue (11603)',
            "#61C680": 'Grass Green (11500)',
            "#68724D": 'Dark Green (11501)',
            "#757575": 'Nardo Gray (11104)',
            "#7D6556": 'Dark Brown (11801)',
            "#950051": 'Plum (11204)',
            "#9B9EA0": 'Ash Gray (11102)',
            "#A3D8E1": 'Ice Blue (11601)',
            "#AE835B": 'Caramel (11803)',
            "#AE96D4": 'Lilac purple (11700)',
            "#B15533": 'Terracotta (11203)',
            "#BB3D43": 'Dark Red (11202)',
            "#C2E189": 'Apple Green (11502)',
            "#CBC6B8": 'Bone White (11103)',
            "#D3B7A7": 'Latte Brown (11800)',
            "#DE4343": 'Scarlet Red (11200)',
            "#E8AFCF": 'Sakura Pink (11201)',
            "#E8DBB7": 'Desert Tan (11401)',
            "#F7D959": 'Lemon Yellow (11400)',
            "#F99963": 'Mandarin Orange (11300)',
            "#FFFFFF": 'Ivory White (11100)',
        },
        "Metal": {
            "#1D7C6A": 'Oxide Green Metallic (13500)',
            "#39699E": 'Cobalt Blue Metallic (13600)',
            "#43403D": 'Iron Gray Metallic (13100)',
            "#AA6443": 'Copper Brown Metallic (13800)',
            "#B39B84": 'Iridium Gold Metallic (13400)',
        },
        "Pure": {
            "#000000": 'Absolute Black (17101)',
            "#A5DAE8": 'Baby Blue (17600)',
            "#F7CDD7": 'Milky Pink (17200)',
            "#FFB672": 'Apricot (17300)',
            "#FFFFFF": 'Pure White (17100)',
        },
        "Silk": {
            "#147BD1": 'Blue (13601)',
            "#4CE4A0": 'Green (13502)',
            "#580490": 'Purple (13701)',
            "#5E4B3C": 'Copper (13300)',
            "#ACB4B5": 'Silver (13104)',
            "#E5B03D": 'Gold (13401)',
            "#EEB1C1": 'Pink (13202)',
            "#FFFFFF": 'White (13105)',
        },
        "Silk Multi-Color": {
            "#000000": 'Velvet Eclipse (Black-Red) (13905)',
            "#0047BB": 'Midnight Blaze (Blue-Red) (13902)',
            "#00629B": 'Phantom Blue (Blue-Black) (13916)',
            "#006EC9": 'Aurora Purple (13909)',
            "#00918B": 'South Beach (13906)',
            "#3A913F": 'Mystic Magenta (Purple+Green) (13913)',
            "#4CE4A0": 'Blue Hawaii (Blue-Green) (13904)',
            "#60A4E8": 'Blue Hawaii (Blue-Green) (13904)',
            "#6CD4BC": 'Dawn Radiance (13912)',
            "#720062": 'Mystic Magenta (Purple+Green) (13913)',
            "#7D1B49": 'Midnight Blaze (Blue-Red) (13902)',
            "#7F3696": 'Aurora Purple (13909)',
            "#A66EB9": 'Dawn Radiance (13912)',
            "#BB22A3": 'Neon City (Blue-Magenta) (13903)',
            "#C80000": 'Velvet Eclipse (Black-Red) (13905)',
            "#D87694": 'Dawn Radiance (13912)',
            "#EC984C": 'Dawn Radiance (13912)',
            "#F772A4": 'South Beach (13906)',
            "#FCA2BF": 'Gilded Rose (Pink-Gold) (13901)',
            "#FF9425": 'Gilded Rose (Pink-Gold) (13901)',
        },
        "Silk+": {
            "#008BDA": 'Blue (13604)',
            "#018814": 'Candy Green (13506)',
            "#5F6367": 'Titan Gray (13108)',
            "#8671CB": 'Purple (13702)',
            "#96DCB9": 'Mint (13507)',
            "#A8C6EE": 'Baby Blue (13603)',
            "#BA9594": 'Rose Gold (13206)',
            "#C8C8C8": 'Silver (13109)',
            "#D02727": 'Candy Red (13205)',
            "#F3CFB2": 'Champagne (13404)',
            "#F4A925": 'Gold (13405)',
            "#F7ADA6": 'Pink (13207)',
            "#FFFFFF": 'White (13110)',
        },
        "Sparkle": {
            "#2D2B28": 'Onyx Black Sparkle (13101)',
            "#3F5443": 'Alpine Green Sparkle (13501)',
            "#483D8B": 'Royal Purple Sparkle (13700)',
            "#792B36": 'Crimson Red Sparkle (13200)',
            "#8E9089": 'Slate Gray Sparkle (13102)',
            "#CEA629": 'Classic Gold Sparkle (13402)',
        },
        "Support": {
            "#000000": 'Support for PLA Black (65101)',
            "#FBF5E4": 'Support for PLA/PETG Natural (65102)',
            "#FFFFFF": 'Support for PLA White (65100)',
        },
        "Tough": {
            "#000000": 'Black',
            "#00482B": 'Pine Green (12500)',
            "#0085AD": 'Light-Blue (12600)',
            "#515A6C": 'Gray (12102)',
            "#6667AB": 'Lavender-Blue (12700)',
            "#9D9D9D": 'Silver (12103)',
            "#DD3C22": 'Vermilion-Red (12200)',
            "#FAFAFA": 'Cream White',
            "#FEDB00": 'Yellow (12400)',
            "#FF7F41": 'Orange (12300)',
            "#FFFFFF": 'White (12100)',
        },
        "Tough+": {
            "#000000": 'Black (12104)',
            "#009BD9": 'Cyan (12601)',
            "#959698": 'Silver (12106)',
            "#AFB1AE": 'Gray (12105)',
            "#DC3A27": 'Orange (12301)',
            "#F4D53F": 'Yellow (12401)',
            "#FFFFFF": 'White (12107)',
        },
        "Translucent": {
            "#0047BB": 'Blue (13611)',
            "#009FA1": 'Teal (13612)',
            "#8344B0": 'Purple (13710)',
            "#96D8AF": 'Light Jade (13510)',
            "#B50011": 'Red (13210)',
            "#B8ACD6": 'Lavender (13711)',
            "#B8CDE9": 'Ice Blue (13610)',
            "#F5B6CD": 'Cherry Pink (13211)',
            "#F5DBAB": 'Mellow Yellow (13410)',
            "#F74E02": 'Orange (13301)',
        },
        "Wood": {
            "#4C241C": 'Rosewood (13204)',
            "#4F3F24": 'Black Walnut (13107)',
            "#918669": 'Classic Birch (13505)',
            "#995F11": 'Clay Brown (13801)',
            "#C98935": 'Ochre Yellow (13403)',
            "#D6CCA3": 'White Oak (13106)',
        },
    },
    "PETG": {
        "Basic": {
            "#000000": 'Black (30101)',
            "#001489": 'Blue (30600)',
            "#0069B1": 'Lake Blue (30602)',
            "#0086D6": 'Navy Blue (30604)',
            "#009639": 'Green (30500)',
            "#034638": 'Pine Green (30503)',
            "#2E4F66": 'Blue Gray (30601)',
            "#4F2C1D": 'Dark Brown (30800)',
            "#688197": 'Misty Blue (30108)',
            "#7CD82B": 'Lime Green (30501)',
            "#7F7E83": 'Gray (30107)',
            "#9E007E": 'Purple (30700)',
            "#ADB1B2": 'Gray (30102)',
            "#D6001C": 'Red (30200)',
            "#D7D7D7": 'Nature (30104)',
            "#DBC8B6": 'Dark Beige (30403)',
            "#EDF0F2": 'White (30100)',
            "#F6D86A": 'Gold (30401)',
            "#FCE300": 'Yellow (30400)',
            "#FF671F": 'Orange (30300)',
            "#FFFFFF": 'White (30106)',
        },
        "CF": {
            "#000000": 'Black (31100)',
            "#16B08E": 'Malachite Green (31500)',
            "#324585": 'Indigo Blue (31600)',
            "#565656": 'Titan Gray (31101)',
            "#583061": 'Violet Purple (31700)',
            "#9F332A": 'Brick Red (31200)',
        },
        "HF": {
            "#000000": 'Black (33102)',
            "#002E96": 'Blue (33600)',
            "#00AE42": 'Green (33500)',
            "#1F79E5": 'Lake Blue (33601)',
            "#39541A": 'Forest Green (33502)',
            "#515151": 'Dark Gray (33103)',
            "#6EE53C": 'Lime Green (33501)',
            "#875718": 'Peanut Brown (33801)',
            "#ADB1B2": 'Gray (33101)',
            "#EB3A3A": 'Red (33200)',
            "#F75403": 'Orange (33300)',
            "#F9DFB9": 'Cream (33401)',
            "#FFD00B": 'Yellow (33400)',
            "#FFFFFF": 'White (33100)',
        },
        "Translucent": {
            "#61B0FF": 'Light Blue (32600)',
            "#748C45": 'Olive (32500)',
            "#77EDD7": 'Teal (32501)',
            "#8E8E8E": 'Gray (32100)',
            "#C9A381": 'Brown (32800)',
            "#D6ABFF": 'Purple (32700)',
            "#EBEBEB": 'Clear (32101)',
            "#F9C1BD": 'Pink (32200)',
            "#FF911A": 'Orange (32300)',
        },
    },
    "TPU": {
        "68D (For AMS)": {
            "#000000": 'Black (53101)',
            "#5898DD": 'Blue (53600)',
            "#90FF1A": 'Neon Green (53500)',
            "#939393": 'Gray (53102)',
            "#ED0000": 'Red (53200)',
            "#F9EF41": 'Yellow (53400)',
            "#FFFFFF": 'White (53100)',
        },
        "85A": {
            "#000000": 'Black (51107)',
            "#C3E2D6": 'Light Cyan (51500)',
            "#EAF28F": 'Lime Green (51501)',
            "#F68B1B": 'Neon Orange (51305)',
            "#FFF2D5": 'Flesh (51201)',
        },
        "90A": {
            "#000000": 'Black (51103)',
            "#40B6E4": 'Frozen (51900)',
            "#5C4738": 'Cocoa Brown (51800)',
            "#7EB4E1": 'Crystal Blue (51601)',
            "#9EA2A2": 'Quicksilver (51106)',
            "#D21B3C": 'Blaze (51901)',
            "#D6ABFF": 'Grape Jelly (51700)',
            "#F1AAA8": 'Blaze (51901)',
            "#FFFFFF": 'White (51105)',
        },
        "95A HF": {
            "#000000": 'Black (51100)',
            "#0072CE": 'Blue (51600)',
            "#898D8D": 'Gray (51101)',
            "#C8102E": 'Red (51200)',
            "#F3E600": 'Yellow (51400)',
            "#FFFFFF": 'White (51102)',
        },
    },
    "ABS": {
        "Basic": {
            "#000000": 'Black (40101)',
            "#00AE42": 'Bambu Green (40500)',
            "#0A2CA5": 'Blue (40600)',
            "#0C2340": 'Navy Blue (40602)',
            "#489FDF": 'Azure (40601)',
            "#7248BD": 'Lavender (40701)',
            "#789D4A": 'Olive (40502)',
            "#87909A": 'Silver (40102)',
            "#8E9089": 'Grey (10103)',
            "#ADF4DC": 'Mint (40501)',
            "#AF1685": 'Purple (40700)',
            "#D32941": 'Red (40200)',
            "#DFD1A7": 'Beige (40401)',
            "#FF6A13": 'Orange (40300)',
            "#FFC72C": 'Tangerine Yellow (40402)',
            "#FFFF20": 'Yellow (40400)',
            "#FFFFFF": 'White (40100)',
        },
        "GF": {
            "#000000": 'Black (41101)',
            "#0C3B95": 'Blue (41600)',
            "#61BF36": 'Green (41500)',
            "#C6C6C6": 'Gray (41102)',
            "#E83100": 'Red (41200)',
            "#F48438": 'Orange (41300)',
            "#FFE133": 'Yellow (41400)',
            "#FFFFFF": 'White (41100)',
        },
    },
    "ASA": {
        "Basic": {
            "#000000": 'Black (45101)',
            "#00A6A0": 'Green (45500)',
            "#2140B4": 'Blue (45600)',
            "#8A949E": 'Gray (45102)',
            "#E02928": 'Red (45200)',
            "#FFFAF2": 'White (45100)',
        },
        "Aero": {
            "#EFF2DE": 'White (46100)',
        },
        "CF": {
            "#000000": 'Black (46101)',
        },
    },
    "PC": {
        "Basic": {
            "#000000": 'Black (60101)',
            "#5A5161": 'Clear Black (60102)',
            "#BFC3C7": 'Transparent (60103)',
            "#FFFFFF": 'White (60100)',
        },
        "FR": {
            "#000000": 'Black (63100)',
            "#A8A8AA": 'Gray (63102)',
            "#FFFFFF": 'White (63101)',
        },
    },
    "PA6": {
        "CF": {
            "#000000": 'Black (72100)',
        },
        "GF": {
            "#000000": 'Black (72104)',
            "#353533": 'Gray (72103)',
            "#5B492F": 'Brown (72800)',
            "#75AED8": 'Blue (72600)',
            "#C5ED48": 'Lime (72500)',
            "#EAEAE4": 'White (72102)',
            "#FF4800": 'Orange (72200)',
            "#FFCE00": 'Yellow (72400)',
        },
    },
    "PAHT": {
        "CF": {
            "#000000": 'Black (70100)',
        },
        "Support": {
            "#C0DF16": 'Support for PA/PET (65500)',
        },
    },
    "PET": {
        "CF": {
            "#000000": 'Black (71100)',
        },
    },
    "PPA": {
        "CF": {
            "#000000": 'Black (73100)',
        },
    },
    "PPS": {
        "CF": {
            "#000000": 'Black (76100)',
        },
    },
    "PVA": {
        "Support": {
            "#F0F1A8": 'Clear (66400)',
        },
    },
    "HIPS": {
        "Support": {
            "#FFFFFF": 'Support for ABS White (66100)',
        },
    },
}

# Hexes no current table carries (old palette holdovers). Last resort.
LEGACY_COLOR_NAMES: dict[str, str] = {
    "#C12E1F": 'Red (10200)',
}


def _line_of(material_table: dict[str, dict[str, str]], product: str | None) -> str | None:
    """Which of the material's product lines the spool's name points at.

    Longest line name first, so "Silk Multi-Color" beats "Silk" and "Tough+"
    beats "Tough". A parenthesised qualifier matches by either half — the
    line "68D (For AMS)" is found in a product called "TPU for AMS".
    """
    if not product:
        return None
    text = str(product)

    def hit(token: str) -> bool:
        pattern = "(^|[^a-z0-9+])" + re.escape(token) + "($|[^a-z0-9+])"
        return re.search(pattern, text, re.I) is not None

    for line in sorted(material_table, key=len, reverse=True):
        tokens = [line] + [p.strip() for p in re.findall(r"\(([^)]+)\)", line)]
        tokens.append(re.sub(r"\s*\([^)]*\)", "", line).strip())
        if any(t and hit(t) for t in tokens):
            return line
    return None


def _in_material(
    material_table: dict[str, dict[str, str]], code: str, product: str | None
) -> str | None:
    """The name within one material: the product's own line first, then
    Basic, then the other lines — a colour is better named with a sibling
    line's code than not at all."""
    line = _line_of(material_table, product)
    order = ([line] if line else []) + ["Basic"] + sorted(material_table)
    seen: set[str] = set()
    for name in order:
        if name in seen or name not in material_table:
            continue
        seen.add(name)
        hit = material_table[name].get(code)
        if hit:
            return hit
    return None


def color_name(
    hex_code: str | None,
    material: str | None = None,
    product: str | None = None,
) -> str:
    """Bambu's name for a colour, or the placeholder when it is not one of theirs.

    The material narrows the answer to the right tables and the product name
    ("Bambu PLA Matte") to the right line within them, because the filament
    code differs per line. Both are optional; without them the tables are
    walked in preference order.
    """
    if not hex_code:
        return UNKNOWN_COLOR
    code = str(hex_code).strip().upper()

    tried: list[str] = []
    if material:
        wanted = str(material).strip().upper()
        # A tray may report a compound like PLA-CF or PA6-GF; the family
        # prefix picks its tables.
        tried = [m for m in COLOR_NAMES_BY_LINE
                 if m == wanted or wanted.startswith(m) or m.startswith(wanted)]
    for m in list(tried) + [m for m in MATERIAL_PREFERENCE if m not in tried]:
        hit = _in_material(COLOR_NAMES_BY_LINE.get(m, {}), code, product)
        if hit:
            return hit
    return LEGACY_COLOR_NAMES.get(code, UNKNOWN_COLOR)


# Every distinct colour name in the palette, for the tags card's colour
# dropdown. Sorted once at import; the palette is fixed per release.
COLOR_NAME_OPTIONS: tuple[str, ...] = tuple(sorted(
    {
        name
        for lines in COLOR_NAMES_BY_LINE.values()
        for hexes in lines.values()
        for name in hexes.values()
    }
    | set(LEGACY_COLOR_NAMES.values())
))
