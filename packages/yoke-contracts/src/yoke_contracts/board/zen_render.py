"""Zen widget — rendering layer.

Rendering character constants, padding/truncation primitives, past- and
future-zone painters, per-project orchestration, and the public
:func:`render_zen_widget` entry point. This is the orchestrator: it pulls
data from :mod:`zen_data` and labels/vision from :mod:`zen_labels`.
"""

from __future__ import annotations

from typing import List, Tuple

from yoke_contracts.board.config import BoardConfig
from yoke_contracts.board.board_db import BoardDBLike
from yoke_contracts.board.zen_data import (
    _WIDTH,
    _zen_check_visibility,
    _zen_compute_window,
    _zen_compute_zones,
    _zen_item_positions,
    _zen_query_items,
    _zen_query_projects,
    _zen_queued_count,
)
from yoke_contracts.board.zen_labels import (
    _parse_extra_stopwords,
    _zen_compute_labels,
)

# -- rendering character constants --------------------------------------------

_DASH = "━"     # ━  BOX DRAWINGS HEAVY HORIZONTAL
_DOT = "●"      # ●  BLACK CIRCLE
_PRESENT = " \U0001f538 "  # 🔸  with surrounding spaces
_DASHED = "╌"   # ╌  BOX DRAWINGS LIGHT DOUBLE DASH HORIZONTAL
_DOTTED = "┄"   # ┄  BOX DRAWINGS LIGHT TRIPLE DASH HORIZONTAL
_MIDDLE_DOT = "·"  # ·
_TILDE = "~"


# -- public entry point --------------------------------------------------------

def render_zen_widget(
    db: BoardDBLike,
    config: BoardConfig,
    scope: str,
    active_count: int,
    pipeline_count: int,
    backlog_count: int,
    vision_entries: List[Tuple[str, str]] = (),
) -> List[str]:
    """Return timeline widget lines, or ``[]`` when hidden.

    Parameters
    ----------
    db:
        Open board database handle.
    config:
        Parsed board config (``timeline_widget`` field controls visibility).
    scope:
        ``all`` for a global board, otherwise one project id.
    active_count:
        Number of active items (for idle visibility check).
    pipeline_count:
        Number of pipeline items (for idle visibility check).
    backlog_count:
        Number of backlog items (for idle visibility check).
    vision_entries:
        ``(key, label)`` pairs from the caller's rendered VISION strategy
        doc (a client-local file). Injected — never read from cwd — so
        the zone layout, which feeds the timeline-position SQL, is fully
        determined by the caller's inputs on both the record and replay
        sides of the board data layer.
    """
    if not _zen_check_visibility(
        config.timeline_widget, active_count, pipeline_count, backlog_count
    ):
        return []

    projects = _zen_query_projects(db, scope)
    if not projects:
        return []

    vision_entries = list(vision_entries)
    vision_count = len(vision_entries)

    lines: List[str] = []

    label_days = max(0, int(config.timeline_label_days or 0))
    df_cap_pct = max(0, int(config.timeline_label_df_cap_pct or 0))
    extra_stops = _parse_extra_stopwords(config.timeline_extra_stopwords)
    min_labels = max(0, int(config.timeline_label_min or 0))

    first = True
    for pid, emoji in projects:
        if not first:
            lines.append("")
        first = False
        # Vision applies only to the "yoke" project
        if pid == "yoke":
            project_lines = _zen_render_project(
                db, pid, emoji, _WIDTH, vision_entries, vision_count,
                label_days, df_cap_pct, extra_stops, min_labels,
            )
        else:
            project_lines = _zen_render_project(
                db, pid, emoji, _WIDTH, [], 0,
                label_days, df_cap_pct, extra_stops, min_labels,
            )
        lines.extend(project_lines)

    return lines


# -- rendering helpers ---------------------------------------------------------

def _pad(n: int, char: str) -> str:
    """Return *n* copies of *char*."""
    return char * n


def _truncate(s: str, maxlen: int) -> str:
    return s[:maxlen]


def _render_past_line(width: int, positions: List[int]) -> str:
    """Render past zone: ━ with ● at dot positions."""
    if not positions:
        return _DASH * width

    parts: List[str] = []
    prev = 0
    for pos in positions:
        pos = max(0, min(pos, width - 1))
        gap = pos - prev
        if gap > 0:
            parts.append(_DASH * gap)
        parts.append(_DOT)
        prev = pos + 1

    tail = width - prev
    if tail > 0:
        parts.append(_DASH * tail)
    return "".join(parts)


def _render_future_zone(width: int, char: str, has_dot: bool) -> str:
    """Render a future zone, optionally placing a dot at the midpoint."""
    if has_dot and width >= 3:
        half = width // 2
        return char * half + _DOT + char * (width - half - 1)
    return char * width


# -- per-project rendering ----------------------------------------------------

def _zen_render_project(
    db: BoardDBLike,
    project: str,
    emoji: str,
    width: int,
    vision_entries: List[Tuple[str, str]],
    vision_count: int,
    label_days: int = 0,
    df_cap_pct: int = 0,
    extra_stops: frozenset = frozenset(),
    min_labels: int = 0,
) -> List[str]:
    """Render a single project timeline (2 lines: pathway + labels)."""
    window = _zen_compute_window(db, project)
    if not window:
        return []

    items = _zen_query_items(db, project, window)
    if not items:
        return []

    queued = _zen_queued_count(db, project)
    has_queued = queued > 0

    zones = _zen_compute_zones(width, True, has_queued, vision_count)
    past_width = 80  # default
    for zname, zwidth, _zcol in zones:
        if zname == "past":
            past_width = zwidth
            break

    future_width = width - 4 - past_width - 4  # 4 emoji, 4 present
    if future_width < 0:
        future_width = 0

    labels = _zen_compute_labels(
        db, project, window, label_days, df_cap_pct, extra_stops, min_labels
    )
    positions = _zen_item_positions(db, project, window, past_width)

    # LINE 1: emoji + pathway
    line1 = _render_pathway(
        emoji, past_width, future_width, has_queued,
        vision_entries, vision_count, positions,
    )

    # LINE 2: feature labels
    line2 = _render_labels(
        labels, past_width, future_width, has_queued,
        queued, vision_entries, vision_count,
    )

    return [line1, line2]


def _render_pathway(
    emoji: str,
    past_width: int,
    future_width: int,
    has_queued: bool,
    vision_entries: List[Tuple[str, str]],
    vision_count: int,
    positions: List[int],
) -> str:
    """Render LINE 1: emoji + pathway with zone chars."""
    parts: List[str] = []

    # Emoji prefix
    parts.append(emoji)

    # Past zone
    parts.append(_render_past_line(past_width, positions))

    # Present marker
    parts.append(_PRESENT)

    # Future zones
    if has_queued or vision_entries:
        fzones = (1 if has_queued else 0) + vision_count
        if fzones == 0:
            fzones = 1
        per = future_width // fzones
        if per < 3:
            per = 3

        if has_queued:
            parts.append(_DASHED * per)

        for idx, (_vk, _vl) in enumerate(vision_entries):
            if idx == 0:
                parts.append(_render_future_zone(per, _DOTTED, True))
            elif idx == 1:
                parts.append(_render_future_zone(per, _MIDDLE_DOT, True))
            else:
                parts.append(_render_future_zone(per, _TILDE, True))

    return "".join(parts)


def _render_labels(
    labels: List[str],
    past_width: int,
    future_width: int,
    has_queued: bool,
    queued_count: int,
    vision_entries: List[Tuple[str, str]],
    vision_count: int,
) -> str:
    """Render LINE 2: feature labels + future labels."""
    parts: List[str] = []

    # 4-char indent (aligns with emoji column)
    parts.append("    ")

    # Past zone labels
    printed = 0
    if labels:
        count = len(labels)
        per = past_width // count
        if per < 3:
            per = 3

        for idx, lab in enumerate(labels):
            if per >= 12:
                show = _truncate(lab, 12)
            elif per >= 6:
                show = _truncate(lab, per - 1)
            elif per >= 3:
                show = _truncate(lab, 2)
            else:
                show = "."

            if idx == count - 1:
                # Last label fills remaining past width
                last_w = past_width - printed
                parts.append(show.ljust(last_w))
                printed = past_width
            else:
                parts.append(show.ljust(per))
                printed += per

    # Pad remaining past zone space
    remain = past_width - printed
    if remain > 0:
        parts.append(" " * remain)

    # Present marker spacing (4 cols)
    parts.append("    ")

    # Future labels
    if has_queued or vision_entries:
        fzones = (1 if has_queued else 0) + vision_count
        if fzones == 0:
            fzones = 1
        per_fl = future_width // fzones
        if per_fl < 3:
            per_fl = 3

        if has_queued:
            parts.append(f"{queued_count}q".ljust(per_fl))

        for _vk, vl in vision_entries:
            vs = _truncate(vl, per_fl - 1)
            parts.append(vs.ljust(per_fl))

    return "".join(parts)


__all__ = [
    "render_zen_widget",
]
