"""Frontier-mode progress fill — replace W-cells proportionally by status counts."""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from yoke_contracts.project_contract.board_art.config import (
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

# Status fill order (most complete first)
# Bucket names renamed to current vocabulary.
_FILL_ORDER = [
    ("done", C_DONE),
    ("release", C_RELEASE),
    ("implemented", C_IMPLEMENTED),
    ("reviewing", C_REVIEWING),
    ("implementing", C_IMPLEMENTING),
    ("blocked", C_BLOCKED),
    ("refined", C_REFINED),
    ("planning", C_PLANNING),
    ("idea", C_IDEA),
]


def _fill_progress(
    grid_lines: List[str],
    counts: Dict[str, int],
    celebration: Optional[str] = None,
) -> List[str]:
    """Replace W-cells proportionally by status counts.

    Count total W-cells, allocate each status proportionally, put any
    rounding remainder on the largest category, then fill left-to-right
    and top-to-bottom (sorted by column, then row).
    """
    total_n = counts.get("total", 0)
    if total_n <= 0:
        return grid_lines

    # Collect all W-cell positions as (byte_offset, line_idx)
    positions: List[Tuple[int, int]] = []
    for line_idx, line in enumerate(grid_lines):
        start = 0
        while True:
            pos = line.find(WHITE, start)
            if pos < 0:
                break
            positions.append((pos, line_idx))
            start = pos + len(WHITE)

    total_whites = len(positions)
    if total_whites == 0:
        return grid_lines

    # Calculate fill counts; floor non-zero categories to at least 1 cell so
    # small active states (e.g. 1 idea against 1800 done) aren't truncated to
    # 0 and erased from the rendered art.
    fill_counts: Dict[str, int] = {}
    for key, _ in _FILL_ORDER:
        n = counts.get(key, 0)
        raw = int(n * total_whites / total_n)
        if n > 0 and raw == 0:
            raw = 1
        fill_counts[key] = raw

    # Reconcile to total_whites: dump remainder on the largest category, or
    # if flooring pushed us over (only possible on tiny grids), pull back.
    filled = sum(fill_counts.values())
    if filled < total_whites:
        max_key = max(fill_counts, key=lambda k: fill_counts[k])
        fill_counts[max_key] += total_whites - filled
    elif filled > total_whites:
        max_key = max(fill_counts, key=lambda k: fill_counts[k])
        fill_counts[max_key] = max(0, fill_counts[max_key] - (filled - total_whites))

    # Build cumulative thresholds
    thresholds: List[Tuple[int, str]] = []
    cum = 0
    for key, color in _FILL_ORDER:
        cum += fill_counts.get(key, 0)
        thresholds.append((cum, color))

    # Sort positions: by column (byte offset) first, then by row
    positions.sort(key=lambda p: (p[0], p[1]))

    # Override done color if celebrating
    done_color = celebration if celebration else C_DONE

    # Build per-line replacement maps
    replacements: Dict[int, List[Tuple[int, str]]] = {}
    for i, (pos, line_idx) in enumerate(positions):
        color = C_REFINED  # default fallback
        for threshold, c in thresholds:
            if i < threshold:
                color = c
                break
        if color == C_DONE and celebration:
            color = done_color
        replacements.setdefault(line_idx, []).append((pos, color))

    # Apply replacements (right to left to preserve byte offsets)
    result = list(grid_lines)
    for line_idx, repls in replacements.items():
        line = result[line_idx]
        # Sort descending by position
        for pos, color in sorted(repls, key=lambda r: r[0], reverse=True):
            line = line[:pos] + color + line[pos + len(WHITE):]
        result[line_idx] = line

    return result
