#!/usr/bin/env python3
"""Convert a PNG/JPEG image into a Yoke board-art emoji block.

Intended use: during project onboarding an operator supplies a logo/image and
Yoke renders it into a `MIXED_EMOJI_COLUMNS`-style emoji block for board art.

Defaults (chosen after a bake-off across palettes, downsamplers, and sizes):
  * palette    = "hybrid" — the 9 universal color squares plus 🩷/🩵 for the two
                 hues squares can't reach (pink, light blue). "mine" = squares
                 only (strictest universality). See the universality note below.
  * downsample = "mode" — majority-vote each cell over its source pixels, so thin
                 anti-alias edges are outvoted (no speckle / phantom tints).
                 "mean" = area-average (softer, but muddies edges).
  * background = white — transparent pixels composite over white, not black.
  * size       = aspect-preserving, capped at 20x20 (max dimension 20).

Pipeline: read dims -> choose grid (aspect-preserving, <= dimension box / area
cap) -> downsample (mode or mean) -> map each cell to nearest palette emoji ->
emit block. Decode (Pillow or sips->BMP) lives in image_to_emoji_art_decode.

Universality note: the color squares are the oldest, render-everywhere glyphs.
🩷 (U+1FA77) and 🩵 (U+1FA75) are Unicode 15 (2023) — they render on current
macOS/iOS/Android but may be missing on older systems. Use ``--palette mine``
for the strictest cross-platform guarantee.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from typing import Dict, List, Sequence, Tuple

# Decode + alpha-compositing live in a sibling module (authored-file line cap);
# re-exported here so the public API stays stable for callers/tests.
from yoke_contracts.project_contract.board_art.image_decode import (  # noqa: F401
    RGB,
    composite,
    image_dimensions,
    load_grid,
    load_native,
)

# --- Master-map area (single source of truth; not duplicated) ----------------
from yoke_contracts.project_contract.board_art._data import _MASTER_MAP_GLYPHS
from yoke_contracts.project_contract.board_art.render_seed import (
    CURRENT_YOKE_MASTER_MAP_COLUMNS,
)

_GLYPH_ROWS = len(next(iter(_MASTER_MAP_GLYPHS.values())))  # 12
MASTER_MAP_COLS = CURRENT_YOKE_MASTER_MAP_COLUMNS  # 47
MASTER_MAP_ROWS = _GLYPH_ROWS + 2  # + top & bottom border rows = 14
MASTER_MAP_AREA = MASTER_MAP_COLS * MASTER_MAP_ROWS  # 658 emoji cells

# --- Palettes: emoji -> approximate rendered sRGB ----------------------------
# The 9 Emoji_Presentation=Yes color squares (RGB ~ Apple's rendering).
PALETTE_SQUARES: List[Tuple[str, RGB]] = [
    ("⬛", (45, 48, 54)),
    ("⬜", (233, 234, 236)),
    ("🟥", (220, 56, 47)),
    ("🟧", (242, 148, 37)),
    ("🟨", (247, 202, 70)),
    ("🟩", (120, 177, 89)),
    ("🟦", (83, 156, 222)),
    ("🟪", (157, 112, 199)),
    ("🟫", (138, 89, 55)),
]
# Hybrid adds the two hues squares can't reach. Heart glyphs are the only
# single-codepoint pink / light-blue available (see universality note above).
PALETTE_HYBRID: List[Tuple[str, RGB]] = PALETTE_SQUARES + [
    ("🩷", (244, 170, 205)),  # pink
    ("🩵", (150, 210, 240)),  # light blue
]
PALETTES: Dict[str, List[Tuple[str, RGB]]] = {
    "mine": PALETTE_SQUARES,
    "hybrid": PALETTE_HYBRID,
}

# --- Defaults (all CLI-configurable) ----------------------------------------
DEFAULT_PALETTE = "hybrid"
DEFAULT_DOWNSAMPLE = "mode"
DEFAULT_AREA_FRACTION = None  # opt-in; default caps by the dimension box
DEFAULT_MIN_W, DEFAULT_MAX_W = 6, 20
DEFAULT_MIN_H, DEFAULT_MAX_H = 6, 20
DEFAULT_MIN_ASPECT, DEFAULT_MAX_ASPECT = 0.45, 2.6  # w/h
DEFAULT_ASPECT_TOLERANCE = 0.10


# --- Color distance (redmean: cheap, perceptual-ish, no deps) ----------------
def color_distance(a: RGB, b: RGB) -> float:
    rm = (a[0] + b[0]) / 2.0
    dr, dg, db = a[0] - b[0], a[1] - b[1], a[2] - b[2]
    return (2 + rm / 256) * dr * dr + 4 * dg * dg + (2 + (255 - rm) / 256) * db * db


def nearest_emoji(rgb: RGB, palette: Sequence[Tuple[str, RGB]]) -> str:
    return min(palette, key=lambda pe: color_distance(rgb, pe[1]))[0]


# --- Grid sizing -------------------------------------------------------------
def choose_grid(
    img_w: int,
    img_h: int,
    *,
    max_area: int,
    min_w: int,
    max_w: int,
    min_h: int,
    max_h: int,
    min_aspect: float,
    max_aspect: float,
    aspect_tolerance: float = 0.10,
) -> Tuple[int, int]:
    """Pick (gw, gh): aspect-preserving (clamped to [min,max] ratio), as large as
    the dimension box and area cap allow. Within ``aspect_tolerance`` of the
    target aspect it fills the budget; else it falls back to the most faithful
    aspect. Area is a hard cap; the aspect range is always enforced."""
    if img_w <= 0 or img_h <= 0:
        raise ValueError("image dimensions must be positive")
    img_aspect = img_w / img_h
    target = min(max(img_aspect, min_aspect), max_aspect)

    def best_in(alo: float, ahi: float, key):
        chosen = None
        chosen_key = None
        for gh in range(min_h, max_h + 1):
            for gw in range(min_w, max_w + 1):
                area = gw * gh
                if area > max_area:
                    continue
                ar = gw / gh
                if ar < alo or ar > ahi:
                    continue
                k = key(ar, area)
                if chosen_key is None or k > chosen_key:
                    chosen_key, chosen = k, (gw, gh)
        return chosen

    lo = max(min_aspect, target * (1 - aspect_tolerance))
    hi = min(max_aspect, target * (1 + aspect_tolerance))
    best = best_in(lo, hi, lambda ar, area: (area, -abs(ar - target)))
    if best is None:
        best = best_in(
            min_aspect, max_aspect,
            lambda ar, area: (-round(abs(ar - target), 3), area),
        )
    if best is None:
        raise SystemExit(
            "No emoji grid satisfies the constraints. Relax --max-area, the "
            "min/max width/height, or the aspect range."
        )
    return best


# --- Render ------------------------------------------------------------------
def boost_saturation(rgb: RGB, factor: float) -> RGB:
    """Push a color away from its gray (luma) by ``factor``. >1 saturates so
    muted colors reach a real palette hue. factor 1.0 is a no-op."""
    if factor == 1.0:
        return rgb
    luma = 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]
    return tuple(  # type: ignore[return-value]
        max(0, min(255, round(luma + (c - luma) * factor))) for c in rgb
    )


def to_block(
    grid: Sequence[Sequence[RGB]],
    palette: Sequence[Tuple[str, RGB]],
    *,
    saturate: float = 1.0,
) -> str:
    """mean path: one mapped emoji per already-downsampled cell."""
    return "\n".join(
        "".join(nearest_emoji(boost_saturation(px, saturate), palette) for px in row)
        for row in grid
    )


def mode_block(
    native: Sequence[Sequence[RGB]],
    gw: int,
    gh: int,
    palette: Sequence[Tuple[str, RGB]],
    *,
    saturate: float = 1.0,
) -> str:
    """mode path: majority-vote each cell over its source pixels. Minority
    anti-alias edge pixels are outvoted, so flat regions stay clean and thin
    sub-cell features drop rather than blending into phantom tints."""
    h = len(native)
    w = len(native[0]) if h else 0
    if w == 0 or h == 0:
        raise SystemExit("empty image")
    rows: List[str] = []
    for cy in range(gh):
        y0, y1 = cy * h // gh, (cy + 1) * h // gh
        if y1 <= y0:  # grid taller than source: sample the nearest single row
            y1 = y0 + 1
        line: List[str] = []
        for cx in range(gw):
            x0, x1 = cx * w // gw, (cx + 1) * w // gw
            if x1 <= x0:  # grid wider than source: sample the nearest column
                x1 = x0 + 1
            votes: Counter = Counter()
            for y in range(y0, y1):
                row = native[y]
                for x in range(x0, x1):
                    votes[nearest_emoji(boost_saturation(row[x], saturate), palette)] += 1
            line.append(votes.most_common(1)[0][0])
        rows.append("".join(line))
    return "\n".join(rows)


def to_tuple_entry(block: str) -> str:
    """Render the block as a ready-to-paste MIXED_EMOJI_COLUMNS entry."""
    return '    """\\\n' + block + '\n""",'


# --- CLI ---------------------------------------------------------------------
def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("image", help="path to a PNG or JPEG image")
    p.add_argument("--palette", choices=sorted(PALETTES), default=DEFAULT_PALETTE,
                   help="emoji palette (default %s; 'mine' = squares only, most "
                        "universal)" % DEFAULT_PALETTE)
    p.add_argument("--downsample", choices=("mode", "mean"),
                   default=DEFAULT_DOWNSAMPLE,
                   help="mode = majority-vote (crisp), mean = area-average "
                        "(default %s)" % DEFAULT_DOWNSAMPLE)
    p.add_argument("--area-fraction", type=float, default=DEFAULT_AREA_FRACTION,
                   help="cap area as a fraction of the master map (e.g. 0.5 = the "
                        "'-50%%' rule); default caps by the dimension box instead")
    p.add_argument("--max-area", type=int, default=None,
                   help="explicit max area in cells (overrides --area-fraction)")
    p.add_argument("--min-width", type=int, default=DEFAULT_MIN_W)
    p.add_argument("--max-width", type=int, default=DEFAULT_MAX_W)
    p.add_argument("--min-height", type=int, default=DEFAULT_MIN_H)
    p.add_argument("--max-height", type=int, default=DEFAULT_MAX_H)
    p.add_argument("--min-aspect", type=float, default=DEFAULT_MIN_ASPECT)
    p.add_argument("--max-aspect", type=float, default=DEFAULT_MAX_ASPECT)
    p.add_argument("--aspect-tolerance", type=float, default=DEFAULT_ASPECT_TOLERANCE,
                   help="aspect drift allowed to fill the budget (0 = pixel-faithful)")
    p.add_argument("--bg", default="255,255,255",
                   help="background RGB for transparent pixels (default white)")
    p.add_argument("--saturate", type=float, default=1.0,
                   help="saturation boost before quantizing (>1 rescues pastels)")
    p.add_argument("--tuple", action="store_true",
                   help="also print the MIXED_EMOJI_COLUMNS tuple entry")
    p.add_argument("--out", default=None, help="write the block to this file")
    args = p.parse_args(argv)

    bg = tuple(int(v) for v in args.bg.split(","))  # type: ignore[assignment]
    if args.max_area is not None:
        max_area = args.max_area
    elif args.area_fraction is not None:
        max_area = int(MASTER_MAP_AREA * args.area_fraction)
    else:
        max_area = args.max_width * args.max_height  # dimension box governs
    palette = PALETTES[args.palette]

    iw, ih = image_dimensions(args.image)
    gw, gh = choose_grid(
        iw, ih, max_area=max_area,
        min_w=args.min_width, max_w=args.max_width,
        min_h=args.min_height, max_h=args.max_height,
        min_aspect=args.min_aspect, max_aspect=args.max_aspect,
        aspect_tolerance=args.aspect_tolerance,
    )

    if args.downsample == "mode":
        block = mode_block(load_native(args.image, bg=bg), gw, gh, palette,
                           saturate=args.saturate)
    else:
        block = to_block(load_grid(args.image, gw, gh, bg=bg), palette,
                         saturate=args.saturate)

    print(
        f"source {iw}x{ih} (aspect {iw/ih:.2f}) -> grid {gw}x{gh} = {gw*gh} cells  "
        f"palette={args.palette} downsample={args.downsample} (area cap {max_area})",
        file=sys.stderr,
    )
    print(block)
    if args.tuple:
        print("\n" + to_tuple_entry(block))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(block + "\n")
        print(f"wrote {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
