"""Generate the Bambu Print Costs icon as SVG + PNG.

Both marks come from the supplied SVGs rather than being redrawn. The Bambu
mark is straight lines, so it stays polygons; the euro has bezier curves, so it
is flattened for the raster while the SVG keeps the original path under the
same transform. One set of numbers drives both, so they cannot drift apart.
"""

import math
import os
import re

from PIL import Image, ImageDraw

_HERE = os.path.dirname(os.path.abspath(__file__))
BAMBU_SRC = os.environ.get("BAMBU_SVG", os.path.join(_HERE, "sources", "bambu-lab-logo.svg"))
EURO_SRC = os.environ.get("EURO_SVG", os.path.join(_HERE, "sources", "euro-sign.svg"))

GREEN = "#00AE42"      # Bambu green
BLUE = "#003399"       # official EU blue

SIZE = 512
SS = 4                 # supersample factor
PAD = 0.045            # margin as a fraction of the artwork

MARK_H_PX = 430        # the Bambu mark's height in working units
EURO_FRAC = 0.50       # euro height, as a fraction of the mark's
EURO_AT = (0.94, 0.84) # euro centre, as a fraction of the mark's box
TILT = 40              # degrees CLOCKWISE — the whole glyph leans, bars included

# The euro file wraps its path in this layer transform.
EURO_LAYER = (-221.22, -366.41)


# ── path parsing ──────────────────────────────────────────────────────────────
def flatten(d: str, steps: int = 24) -> list[list[tuple[float, float]]]:
    """Path data to polygons. Supports M/L/H/V/C/Z; cubics are subdivided."""
    tok = re.findall(r"[MmLlHhVvCcZz]|-?\d*\.?\d+(?:[eE]-?\d+)?", d)
    polys: list[list[tuple[float, float]]] = []
    cur: list[tuple[float, float]] = []
    x = y = 0.0
    start = (0.0, 0.0)
    cmd = None
    i = 0

    def num() -> float:
        nonlocal i
        v = float(tok[i])
        i += 1
        return v

    def cubic(x0, y0, x1, y1, x2, y2, x3, y3):
        for s in range(1, steps + 1):
            t = s / steps
            u = 1 - t
            cur.append((
                u**3 * x0 + 3 * u * u * t * x1 + 3 * u * t * t * x2 + t**3 * x3,
                u**3 * y0 + 3 * u * u * t * y1 + 3 * u * t * t * y2 + t**3 * y3,
            ))

    while i < len(tok):
        if tok[i] in "MmLlHhVvCcZz":
            cmd = tok[i]
            i += 1
            if cmd in "Zz":
                if cur:
                    polys.append(cur)
                    cur = []
                x, y = start
                continue
        rel = cmd.islower()
        if cmd in "Mm":
            nx, ny = num(), num()
            x, y = (x + nx, y + ny) if rel else (nx, ny)
            if cur:
                polys.append(cur)
            cur = [(x, y)]
            start = (x, y)
            cmd = "l" if rel else "L"          # implicit lineto after a moveto
        elif cmd in "Ll":
            nx, ny = num(), num()
            x, y = (x + nx, y + ny) if rel else (nx, ny)
            cur.append((x, y))
        elif cmd in "Hh":
            nx = num()
            x = x + nx if rel else nx
            cur.append((x, y))
        elif cmd in "Vv":
            ny = num()
            y = y + ny if rel else ny
            cur.append((x, y))
        elif cmd in "Cc":
            a, b, c, e, f, g = (num() for _ in range(6))
            if rel:
                a, b, c, e, f, g = x + a, y + b, x + c, y + e, x + f, y + g
            cubic(x, y, a, b, c, e, f, g)
            x, y = f, g
        else:
            raise ValueError(f"unsupported path command {cmd!r}")
    if cur:
        polys.append(cur)
    return polys


def bbox(polys):
    xs = [p[0] for poly in polys for p in poly]
    ys = [p[1] for poly in polys for p in poly]
    return min(xs), min(ys), max(xs), max(ys)


# ── the two marks ─────────────────────────────────────────────────────────────
def bambu_mark():
    """path4491's first four subpaths — the logo mark, before the wordmark."""
    svg = open(BAMBU_SRC, encoding="utf-8").read()
    d = re.search(r'id="path4491"[^>]*?\sd="([^"]+)"', svg, re.S).group(1)
    polys = flatten(d[: d.index("M -193.98192")])
    x0, y0, _x1, y1 = bbox(polys)
    k = MARK_H_PX / (y1 - y0)
    return [[((x - x0) * k, (y - y0) * k) for x, y in poly] for poly in polys]


def euro_path() -> str:
    svg = open(EURO_SRC, encoding="utf-8").read()
    return re.search(r'id="path2100"[^>]*?\sd="([^"]+)"', svg, re.S).group(1)


MARK = bambu_mark()
MARK_W = max(x for poly in MARK for x, _ in poly)
MARK_H = max(y for poly in MARK for _, y in poly)

_EURO_RAW = flatten(euro_path())
_EURO_LAYERED = [[(x + EURO_LAYER[0], y + EURO_LAYER[1]) for x, y in p] for p in _EURO_RAW]
_EX0, _EY0, _EX1, _EY1 = bbox(_EURO_LAYERED)

EURO_K = (MARK_H * EURO_FRAC) / (_EY1 - _EY0)
EURO_W = (_EX1 - _EX0) * EURO_K
EURO_H = (_EY1 - _EY0) * EURO_K
EURO_CX = MARK_W * EURO_AT[0]
EURO_CY = MARK_H * EURO_AT[1]
EURO_TX = EURO_CX - EURO_W / 2          # top-left of the placed glyph
EURO_TY = EURO_CY - EURO_H / 2


def place_euro(pt):
    """Scale, position, then tilt the whole glyph about its own centre."""
    x = (pt[0] - _EX0) * EURO_K + EURO_TX
    y = (pt[1] - _EY0) * EURO_K + EURO_TY
    a = math.radians(TILT)                       # +ve = clockwise, y down
    dx, dy = x - EURO_CX, y - EURO_CY
    return (
        EURO_CX + dx * math.cos(a) - dy * math.sin(a),
        EURO_CY + dx * math.sin(a) + dy * math.cos(a),
    )


EURO = [[place_euro(p) for p in poly] for poly in _EURO_LAYERED]


# ── output ────────────────────────────────────────────────────────────────────
def render(size: int) -> Image.Image:
    k = size * SS / SIZE
    span = max(MARK_W, MARK_H) + EURO_W * 2
    img = Image.new("RGBA", (int(span * k), int(span * k)), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    for poly in MARK:
        d.polygon([(x * k, y * k) for x, y in poly], fill=GREEN)
    for poly in EURO:
        d.polygon([(x * k, y * k) for x, y in poly], fill=BLUE)

    art = img.crop(img.getbbox())
    side = max(art.size)
    pad = int(side * PAD)
    canvas = Image.new("RGBA", (side + 2 * pad, side + 2 * pad), (0, 0, 0, 0))
    canvas.paste(art, ((canvas.width - art.width) // 2, (canvas.height - art.height) // 2), art)
    return canvas.resize((size, size), Image.LANCZOS)


def svg_text() -> str:
    polys = "\n".join(
        '    <polygon points="%s"/>' % " ".join(f"{x:.2f},{y:.2f}" for x, y in poly)
        for poly in MARK
    )
    x0, y0, x1, y1 = bbox(MARK + EURO)
    m = max(x1 - x0, y1 - y0) * PAD
    side = max(x1 - x0, y1 - y0) + 2 * m
    vx = x0 - m - (side - (x1 - x0) - 2 * m) / 2
    vy = y0 - m - (side - (y1 - y0) - 2 * m) / 2

    # Right-to-left: layer offset, origin, scale, place, then tilt.
    tf = (
        f"rotate({TILT} {EURO_CX:.2f} {EURO_CY:.2f}) "
        f"translate({EURO_TX:.2f} {EURO_TY:.2f}) "
        f"scale({EURO_K:.6f}) "
        f"translate({-_EX0:.2f} {-_EY0:.2f}) "
        f"translate({EURO_LAYER[0]} {EURO_LAYER[1]})"
    )
    return f"""<svg xmlns="http://www.w3.org/2000/svg"
     viewBox="{vx:.2f} {vy:.2f} {side:.2f} {side:.2f}"
     width="512" height="512" role="img" aria-label="Bambu Print Costs">
  <g fill="{GREEN}">
{polys}
  </g>
  <path fill="{BLUE}" transform="{tf}"
        d="{euro_path()}"/>
</svg>
"""


if __name__ == "__main__":
    import sys

    out = sys.argv[1]
    open(f"{out}/icon.svg", "w", encoding="utf-8", newline="\n").write(svg_text())
    render(256).save(f"{out}/icon.png")
    render(512).save(f"{out}/icon@2x.png")
    print(f"mark {MARK_W:.0f}x{MARK_H:.0f}, euro {EURO_W:.0f}x{EURO_H:.0f}, tilt {TILT} clockwise")
