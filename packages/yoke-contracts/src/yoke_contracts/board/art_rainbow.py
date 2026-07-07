"""Rainbow fill modes — random, letters, halves, gradient, and emoji.

Letter-aware modes (letters/halves/emoji) take a ``letter_bounds`` list of
inclusive ``(lo, hi)`` column spans. When omitted they fall back to the
built-in 6-letter ``LETTER_BOUNDS`` (``YOKE``) geometry, preserving prior
behavior; the renderer passes spans resolved from the master map (declared
``# letters:`` directive or auto-derived) so any word renders correctly.
"""

from __future__ import annotations

import random
from typing import List, Optional, Tuple

from yoke_contracts.project_contract.board_art.config import (
    BLACK,
    EMOJI_SETS,
    LETTER_BOUNDS,
    RAINBOW,
    WHITE,
)

Bounds = List[Tuple[int, int]]


def _bounds_or_default(letter_bounds: Optional[Bounds]) -> Bounds:
    return list(letter_bounds) if letter_bounds else list(LETTER_BOUNDS)


def _mids(bounds: Bounds) -> List[int]:
    """Per-letter horizontal midpoint column (for left/right halves split)."""
    return [(lo + hi) // 2 for lo, hi in bounds]


def _apply_rainbow(
    grid_lines: List[str],
    sub_mode: str,
    rng: random.Random,
    letter_bounds: Optional[Bounds] = None,
) -> List[str]:
    """Dispatch to the appropriate rainbow fill mode."""
    bounds = _bounds_or_default(letter_bounds)
    if sub_mode == "random":
        return _fill_rainbow_random(grid_lines, rng)
    elif sub_mode == "letters":
        return _fill_rainbow_letters(grid_lines, rng, bounds)
    elif sub_mode == "halves":
        return _fill_rainbow_halves(grid_lines, rng, bounds)
    elif sub_mode == "gradient":
        return _fill_rainbow_gradient(grid_lines, rng)
    elif sub_mode == "emoji":
        return _fill_rainbow_emoji(grid_lines, rng, bounds)
    else:
        return _fill_rainbow_random(grid_lines, rng)


def _fill_rainbow_random(grid_lines: List[str], rng: random.Random) -> List[str]:
    """Replace each W-cell with a random rainbow color."""
    result = []
    for line in grid_lines:
        out = []
        i = 0
        while i < len(line):
            if line[i:i + len(WHITE)] == WHITE:
                out.append(rng.choice(RAINBOW))
                i += len(WHITE)
            else:
                out.append(line[i])
                i += 1
        result.append("".join(out))
    return result


def _letter_index(col: int, bounds: Optional[Bounds] = None) -> int:
    """Map emoji column to letter index (0-based) using *bounds*."""
    for li, (lo, hi) in enumerate(_bounds_or_default(bounds)):
        if lo <= col <= hi:
            return li
    return 0


def _fill_rainbow_letters(
    grid_lines: List[str],
    rng: random.Random,
    bounds: Optional[Bounds] = None,
) -> List[str]:
    """Each letter gets a different random color (Fisher-Yates shuffle).

    When there are more letters than palette colors, colors cycle.
    """
    bounds = _bounds_or_default(bounds)
    colors = list(RAINBOW)
    # Fisher-Yates shuffle
    for i in range(len(colors) - 1, 0, -1):
        j = rng.randint(0, i)
        colors[i], colors[j] = colors[j], colors[i]
    n = len(bounds)
    lc = [colors[k % len(colors)] for k in range(n)]

    result = []
    for line in grid_lines:
        out = []
        col = 0
        i = 0
        while i < len(line):
            if line[i:i + len(WHITE)] == WHITE:
                li = _letter_index(col, bounds)
                out.append(lc[li] if li < n else lc[0])
                i += len(WHITE)
                col += 1
            elif line[i:i + len(BLACK)] == BLACK:
                out.append(BLACK)
                i += len(BLACK)
                col += 1
            else:
                out.append(line[i])
                i += 1
        result.append("".join(out))
    return result


def _fill_rainbow_halves(
    grid_lines: List[str],
    rng: random.Random,
    bounds: Optional[Bounds] = None,
) -> List[str]:
    """Each letter split into halves with different colors.

    Randomly chooses top/bottom (split at the grid's vertical middle) or
    left/right (split at each letter's midpoint column).
    """
    bounds = _bounds_or_default(bounds)
    mids = _mids(bounds)
    n = len(bounds)
    split_mode = rng.randint(0, 1)  # 0=top/bottom, 1=left/right
    mid_row = len(grid_lines) // 2

    # 2 colors per letter (ensure they differ)
    hc: List[Tuple[str, str]] = []
    for _ in range(n):
        c1 = rng.randrange(6)
        c2 = rng.randrange(6)
        while c2 == c1:
            c2 = rng.randrange(6)
        hc.append((RAINBOW[c1], RAINBOW[c2]))

    result = []
    for row_idx, line in enumerate(grid_lines):
        out = []
        col = 0
        i = 0
        while i < len(line):
            if line[i:i + len(WHITE)] == WHITE:
                li = _letter_index(col, bounds)
                if split_mode == 0:
                    half = 0 if row_idx < mid_row else 1
                else:
                    half = 0 if col <= mids[li] else 1
                out.append(hc[li][half])
                i += len(WHITE)
                col += 1
            elif line[i:i + len(BLACK)] == BLACK:
                out.append(BLACK)
                i += len(BLACK)
                col += 1
            else:
                out.append(line[i])
                i += 1
        result.append("".join(out))
    return result


def _fill_rainbow_gradient(grid_lines: List[str], rng: random.Random) -> List[str]:
    """Background K-cells get a color gradient; W-cells get a single random color.

    Randomly chooses gradient direction: L-R, T-B, diag-down, diag-up.
    Column count is taken from the actual grid width (any word/size).
    """
    total_rows = len(grid_lines)
    total_cols = max((len(line) for line in grid_lines), default=1)

    # Exclude one random color for letters
    excl = rng.randrange(6)
    letter_color = RAINBOW[excl]
    gpool = [RAINBOW[i] for i in range(6) if i != excl]

    # Gradient direction
    grad_dir = rng.randrange(4)

    # Color order: normal or reversed
    if rng.random() < 0.5:
        grad = list(gpool)
    else:
        grad = list(reversed(gpool))

    result = []
    for row_idx, line in enumerate(grid_lines):
        out = []
        col = 0
        i = 0
        while i < len(line):
            if line[i:i + len(WHITE)] == WHITE:
                out.append(letter_color)
                i += len(WHITE)
                col += 1
            elif line[i:i + len(BLACK)] == BLACK:
                if grad_dir == 0:
                    frac = col / max(total_cols - 1, 1)
                elif grad_dir == 1:
                    frac = row_idx / max(total_rows - 1, 1)
                elif grad_dir == 2:
                    frac = (col + row_idx) / max(total_cols + total_rows - 2, 1)
                else:
                    frac = (col + (total_rows - 1 - row_idx)) / max(
                        total_cols + total_rows - 2, 1
                    )
                gi = int(frac * 4.99)
                gi = max(0, min(4, gi))
                out.append(grad[gi])
                i += len(BLACK)
                col += 1
            else:
                out.append(line[i])
                i += 1
        result.append("".join(out))
    return result


def _fill_rainbow_emoji(
    grid_lines: List[str],
    rng: random.Random,
    bounds: Optional[Bounds] = None,
) -> List[str]:
    """Emoji-themed fill: emoji letters or emoji background.

    Sub-mode 0: emoji letters (each letter a different emoji from themed set),
                black background.
    Sub-mode 1: emoji background (tiled single emoji), colored square letters.
    """
    bounds = _bounds_or_default(bounds)
    emoji_mode = rng.randint(0, 1)
    si = rng.randrange(len(EMOJI_SETS))

    if emoji_mode == 0:
        # Emoji letters
        emo = list(EMOJI_SETS[si])
        # Fisher-Yates shuffle
        for i in range(len(emo) - 1, 0, -1):
            j = rng.randint(0, i)
            emo[i], emo[j] = emo[j], emo[i]
    else:
        # Emoji background
        bg_emoji = EMOJI_SETS[si][rng.randrange(6)]
        letter_color = RAINBOW[rng.randrange(6)]

    result = []
    for line in grid_lines:
        out = []
        col = 0
        i = 0
        while i < len(line):
            if line[i:i + len(WHITE)] == WHITE:
                if emoji_mode == 0:
                    li = _letter_index(col, bounds)
                    out.append(emo[li % len(emo)])
                else:
                    out.append(letter_color)
                i += len(WHITE)
                col += 1
            elif line[i:i + len(BLACK)] == BLACK:
                if emoji_mode == 1:
                    out.append(bg_emoji)
                else:
                    out.append(BLACK)
                i += len(BLACK)
                col += 1
            else:
                out.append(line[i])
                i += 1
        result.append("".join(out))
    return result
