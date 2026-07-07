"""Header rendering — top-level ``render_header`` plus stats box and grid paste."""

from __future__ import annotations

import random
from typing import Dict, List, Optional

from yoke_contracts.project_contract.board_art.emoji import resolve_celebration
from yoke_contracts.project_contract.board_art.config import (
    ArtConfig,
    ArtVariant,
    resolve_letter_bounds,
    BLACK,
    C_BLOCKED,
    C_DONE,
    C_IDEA,
    C_IMPLEMENTED,
    C_IMPLEMENTING,
    C_PLANNING,
    C_REFINED,
    C_RELEASE,
    C_REVIEWING,
    WHITE,
)
from yoke_contracts.board.art_progress import _fill_progress
from yoke_contracts.board.art_rainbow import _apply_rainbow
from yoke_contracts.board.art_stats import _render_stats_box
from yoke_contracts.board.config import BoardConfig
from yoke_contracts.board.board_db import BoardDBLike
from yoke_contracts.board.utils import display_width

# Sentinel: render_header derives the celebration glyph from the seed when the
# caller does not supply one. _assemble passes the shared value so the stats
# box, frontier grid/legend, Done section header, and per-row done all match.
_COMPUTE_CELEBRATION = object()


def render_header(
    db: Optional[BoardDBLike],
    config: BoardConfig,
    art_config: ArtConfig,
    mode: str,
    variant: Optional[ArtVariant],
    frontier_counts: Dict[str, int],
    stats_counts: Optional[Dict[str, int]] = None,
    stats_total: Optional[int] = None,
    seed: Optional[int] = None,
    celebration=_COMPUTE_CELEBRATION,
) -> str:
    """Render the complete header art block.

    Parameters
    ----------
    db : BoardDBLike or None
        Database connection (unused for pure art rendering, may be used for
        future stats queries).
    config : BoardConfig
        Parsed board configuration.
    art_config : ArtConfig
        Parsed art configuration.
    mode : str
        Art mode name from :func:`select_art`.
    variant : ArtVariant or None
        Selected variant (for emoji/ascii/mixed modes).
    frontier_counts : dict
        Status counts for frontier fill and stats box.  Expected keys:
        ``done``, ``implemented``, ``release``, ``reviewing``,
        ``implementing``, ``blocked``, ``refined``, ``planning``,
        ``idea``, ``total``, ``frozen``,
        ``pipeline``, ``backlog``.
    seed : int or None
        Deterministic seed for rainbow fills.

    Returns
    -------
    str
        Complete header art block as a multi-line string.
    """
    rng = random.Random(seed)

    # Letter spans for letter-aware rainbow fills: a declared "# letters:"
    # directive wins, else spans are auto-derived from the master map.
    letter_bounds = resolve_letter_bounds(
        art_config.letter_bounds, art_config.master_map
    )

    # Celebration mode (frontier inbox-zero): resolve the one glyph for this
    # render so it flows to the grid, legend, and stats box. Direct callers
    # (and tests) leave it _COMPUTE and we derive it from the seed; _assemble
    # passes the shared value so the Done section + per-row done stay in sync.
    if celebration is _COMPUTE_CELEBRATION:
        celebration = resolve_celebration(stats_counts or frontier_counts, mode, seed)

    # Determine art type and grid lines
    art_type: str  # "emoji_grid" | "ascii" | "mixed"
    grid_lines: List[str]

    if mode == "frontier":
        grid_lines = list(art_config.master_map)
        grid_lines = _fill_progress(grid_lines, frontier_counts, celebration)
        art_type = "emoji_grid"
    elif mode.startswith("rainbow_"):
        grid_lines = list(art_config.master_map)
        sub_mode = mode[len("rainbow_"):]
        grid_lines = _apply_rainbow(grid_lines, sub_mode, rng, letter_bounds)
        art_type = "emoji_grid"
    elif mode.startswith("emoji_"):
        if variant and variant.lines:
            grid_lines = list(variant.lines)
        else:
            grid_lines = list(art_config.master_map)
            grid_lines = _apply_rainbow(grid_lines, "random", rng, letter_bounds)
        art_type = "emoji_grid"
    elif mode.startswith("ascii_"):
        if variant and variant.lines:
            grid_lines = list(variant.lines)
            art_type = "ascii"
        else:
            grid_lines = list(art_config.master_map)
            grid_lines = _apply_rainbow(grid_lines, "random", rng, letter_bounds)
            art_type = "emoji_grid"
    elif mode.startswith("mixed_"):
        if variant and variant.lines:
            grid_lines = list(variant.lines)
            art_type = "mixed"
        else:
            grid_lines = list(art_config.master_map)
            grid_lines = _apply_rainbow(grid_lines, "random", rng, letter_bounds)
            art_type = "emoji_grid"
    else:
        # Unknown — fallback to rainbow random
        grid_lines = list(art_config.master_map)
        grid_lines = _apply_rainbow(grid_lines, "random", rng, letter_bounds)
        art_type = "emoji_grid"

    # Build stats box from rendered section counts, not frontier-fill counts.
    stats_source = stats_counts if stats_counts is not None else frontier_counts
    if stats_total is None:
        stats_total = frontier_counts.get("total", 0)
    stats_lines = _render_stats_box(stats_source, stats_total, celebration)

    # Append stats box to the right of the art
    if art_type in ("ascii", "mixed"):
        combined = _paste_ascii_with_stats(grid_lines, stats_lines)
    else:
        # Frontier mode keeps the stats box near the top of the art.
        pad = 1 if mode == "frontier" else None
        combined = _paste_grid_with_stats(grid_lines, stats_lines, top_pad=pad)

    # Frontier legend: place on grid rows 10-12 (1-indexed), right of the
    # grid just below the stats box (rows 2-8) with one blank row gap.
    # Split across 3 lines to stay within the stats-box width.
    if mode == "frontier":
        done_legend = celebration if celebration else C_DONE
        legend_1 = (
            f" {done_legend}done {C_RELEASE}release {C_IMPLEMENTED}implemented"
        )
        legend_2 = (
            f" {C_REVIEWING}reviewing"
            f" {C_IMPLEMENTING}implementing {C_BLOCKED}blocked"
        )
        legend_3 = (
            f" {C_REFINED}refined"
            f" {C_PLANNING}planning {C_IDEA}idea"
        )
        # Rows 9-11 (0-indexed) = rows 10-12 (1-indexed)
        if len(combined) >= 12:
            combined[9] = combined[9] + legend_1
            combined[10] = combined[10] + legend_2
            combined[11] = combined[11] + legend_3

    return "\n".join(combined)


# Square-emoji glyph used to back synthetic filler rows. It is the same
# Unicode "geometric shape" emoji family as the art's colored squares
# (🟥🟨🟦🟩) and off-cells (⬛⬜), so it renders at the identical glyph width in
# any font — including emoji-rendering editors (VS Code, GitHub) where a plain
# space does NOT match emoji width. On a dark background it is effectively
# invisible, matching the art's own off-cells.
_FILLER_WIDE_CELL = "⬛"  # ⬛


def _blank_filler_row(padded_lines: List[str]) -> str:
    """Build a width-matched blank row for padding the art below/above the box.

    A plain run of spaces only aligns under all-ASCII art; under wide emoji it
    falls short in editors that render emoji wider than two monospace cells, so
    the box border on the filler row drifts left. Instead, mirror the widest
    art line cell-by-cell: wide (emoji) cells become ``⬛`` (same square-emoji
    width as the art grid), narrow cells become a space. The result has the
    same visual width as the art rows in both terminals and emoji editors.
    """
    template = max(padded_lines, key=display_width, default="")
    return "".join(
        _FILLER_WIDE_CELL if display_width(ch) >= 2 else " " for ch in template
    )


def _paste_grid_with_stats(
    grid_lines: List[str],
    stats_lines: List[str],
    top_pad: Optional[int] = None,
) -> List[str]:
    """Paste stats box to the right of an emoji grid.

    The 7-line stats box is vertically centered when the grid has > 7 rows,
    unless *top_pad* is explicitly provided (e.g. ``1`` for frontier mode).
    """
    art_rows = len(grid_lines)
    box_rows = len(stats_lines)  # 8 since adding the Blocked row

    if art_rows <= box_rows:
        # Box is taller than (or equal to) the art: every box row needs a
        # left margin of uniform display width, otherwise the rows that fall
        # below the art jump to column 0 and the box's left border goes jagged.
        # Measure the art's max visual width (emoji-aware) and pad both the
        # real rows and the synthetic filler rows to it.
        max_width = max((display_width(line) for line in grid_lines), default=0)
        padded = [
            line + " " * (max_width - display_width(line)) for line in grid_lines
        ]
        filler = _blank_filler_row(padded)
        while len(padded) < box_rows:
            padded.append(filler)
        return [g + s for g, s in zip(padded, stats_lines)]

    # Tall grid: use explicit top_pad or center box vertically
    if top_pad is None:
        top_pad = (art_rows - box_rows) // 2
    result: List[str] = []
    for i, g in enumerate(grid_lines):
        box_idx = i - top_pad
        if 0 <= box_idx < box_rows:
            result.append(g + stats_lines[box_idx])
        else:
            result.append(g)
    return result


def _paste_ascii_with_stats(
    art_lines: List[str], stats_lines: List[str]
) -> List[str]:
    """Paste stats box to the right of ASCII/mixed art.

    Pads art lines to uniform visual width before concatenation.
    """
    # Strip trailing whitespace
    stripped = [line.rstrip() for line in art_lines]

    # Measure max visual width using proper emoji-aware display_width
    max_width = 0
    widths: List[int] = []
    for line in stripped:
        w = display_width(line)
        widths.append(w)
        if w > max_width:
            max_width = w

    # Pad each line to uniform display width
    padded = [line + " " * (max_width - w) for line, w in zip(stripped, widths)]

    art_rows = len(padded)
    box_rows = len(stats_lines)

    if art_rows <= box_rows:
        filler = _blank_filler_row(padded)
        while len(padded) < box_rows:
            padded.append(filler)
        return [a + s for a, s in zip(padded, stats_lines)]

    top_pad = (art_rows - box_rows) // 2
    result: List[str] = []
    for i, a in enumerate(padded):
        box_idx = i - top_pad
        if 0 <= box_idx < box_rows:
            result.append(a + stats_lines[box_idx])
        else:
            result.append(a)
    return result
