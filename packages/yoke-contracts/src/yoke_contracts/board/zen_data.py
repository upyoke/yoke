"""Zen widget — data layer.

Constants, visibility check, DB queries, window/position computation, zone
allocation, and the repo-root locator. Pure-data helpers consumed by the
labels and rendering submodules.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from yoke_contracts.board.board_db import BoardDBLike
from yoke_contracts.board.project_scope import project_id_filter, scope_project_id
from yoke_contracts.board.sql import LOCAL_NOW_SQL, elapsed_days_expr, timestamp_expr

# -- constants -----------------------------------------------------------------

_WIDTH = 125
_MAX_LABELS = 10

_STOP_WORDS = frozenset({
    # Articles / prepositions / conjunctions
    "the", "a", "an", "for", "and", "to", "from", "with", "all", "new",
    "in", "of", "is", "by", "as", "on", "at", "or", "if", "but", "that",
    "this", "these", "those", "not", "no",
    # Project / scope tokens
    "yoke", "buzz", "epic", "item", "task", "status",
    # Generic action verbs with no signal ("Make X", "Move Y", …)
    "add", "fix", "update", "make", "move", "give", "change", "reduce",
    "ensure", "handle", "restore", "rename", "enable", "disable", "allow",
    "prevent", "create", "delete", "convert", "avoid", "apply", "treat",
    "include", "extract", "finish", "use", "run", "get", "put", "let",
    "show", "see", "read", "write", "keep", "drop", "stop", "start",
    "expose", "extend", "replace", "teach",
    # Filler
    "full", "set", "up", "off", "back", "down", "over", "out", "one", "two",
    "first", "last", "next", "more", "most", "some", "any",
    "remaining", "still", "only", "even", "also", "just", "very",
})

# VISION.md section map (header -> key)
_VISION_SECTIONS = [
    ("1 Month", "1mo"),
    ("6 Months", "6mo"),
    ("1 Year", "1yr"),
    ("5 Years", "5yr"),
]


# -- visibility ----------------------------------------------------------------

def _zen_check_visibility(
    config_value: str,
    active: int,
    pipeline: int,
    backlog: int,
) -> bool:
    """Return True when the widget should render.

    ``always`` shows the widget, ``never`` hides it, and ``idle`` (or
    anything else) shows only when all three counts are 0.
    """
    if config_value == "always":
        return True
    if config_value == "never":
        return False
    # idle (default)
    return active == 0 and pipeline == 0 and backlog == 0


# -- data queries --------------------------------------------------------------

def _zen_project_id(db: BoardDBLike, project: str | int) -> int:
    return scope_project_id(db, project)


def _zen_query_projects(db: BoardDBLike, scope: str = "all") -> List[Tuple[str, str]]:
    """Projects with done items, ordered by done-count descending.

    Returns ``(project_slug, emoji)`` tuples.
    """
    if not scope or scope == "all":
        scope_sql = project_id_filter("p")
        params = ()
    else:
        scope_sql = "AND p.id = %s"
        params = (_zen_project_id(db, scope),)
    rows = db.query_quiet(
        "SELECT p.slug, COALESCE(p.emoji,'') "
        "FROM projects p "
        "WHERE EXISTS ("
        "  SELECT 1 FROM items i "
        "  WHERE i.project_id = p.id AND i.status = 'done'"
        ") "
        f"{scope_sql} "
        "ORDER BY ("
        "  SELECT COUNT(*) FROM items i "
        "  WHERE i.project_id = p.id AND i.status = 'done'"
        ") DESC",
        params,
    )
    return [(r[0], r[1]) for r in rows]


def _zen_query_items(
    db: BoardDBLike, project: str, window_start: str
) -> List[Tuple]:
    """Done items in scope: ``(id, title, created_at, type)``."""
    project_id = _zen_project_id(db, project)
    return db.query(
        "SELECT id, title, created_at, type "
        "FROM items "
        "WHERE project_id = %s AND status = 'done' AND created_at >= %s "
        "ORDER BY created_at",
        (project_id, window_start),
    )


def _zen_queued_count(db: BoardDBLike, project: str) -> int:
    """Count of queued items for *project*."""
    project_id = _zen_project_id(db, project)
    val = db.scalar(
        "SELECT COUNT(*) FROM items "
        "WHERE project_id = %s "
        "AND (status IN ('idea','planned','refined-idea','refining-idea') "
        "     OR (frozen = 1 "
        "         AND status NOT IN ('done','cancelled','stopped','failed')))",
        (project_id,),
    )
    return int(val) if val else 0


def _zen_compute_window(db: BoardDBLike, project: str) -> Optional[str]:
    """Timeline window start date (``YYYY-MM-DD`` or ``None``)."""
    project_id = _zen_project_id(db, project)
    val = db.scalar(
        "SELECT MIN(created_at) FROM items "
        "WHERE project_id = %s AND status = 'done'",
        (project_id,),
    )
    if val:
        return str(val)[:10]
    return None


def _zen_item_positions(
    db: BoardDBLike, project: str, window_start: str, past_width: int
) -> List[int]:
    """Compute dot positions on the past-zone timeline.

    Ensures minimum 3-char gap between dots for readability.
    """
    # Per-row position fraction computed once in a derived table; the outer
    # query clamps to [0, past_width-1] and dedupes. Deduping via ``DISTINCT``
    # on the computed column keeps the GROUP BY off a bare column.
    created_ts = timestamp_expr("created_at")
    window_ts = "(%s)::timestamp"
    elapsed_from_window = elapsed_days_expr(created_ts, window_ts)
    elapsed_window_span = elapsed_days_expr(LOCAL_NOW_SQL, window_ts)
    project_id = _zen_project_id(db, project)
    rows = db.query(
        "SELECT DISTINCT FLOOR(LEAST(GREATEST(pos_raw, 0), %s))::INTEGER AS pos "
        "FROM ("
        "  SELECT "
        f"    {elapsed_from_window} * %s / GREATEST({elapsed_window_span}, 1) AS pos_raw "
        "  FROM items "
        "  WHERE project_id = %s AND status = 'done' AND created_at >= %s "
        ") sub "
        "ORDER BY pos",
        (
            past_width - 1,
            window_start, past_width, window_start,
            project_id, window_start,
        ),
    )

    raw = [int(r[0]) for r in rows if r[0] is not None]
    if not raw:
        return []

    # Enforce minimum gap of 3
    filtered: List[int] = []
    last = -999
    for pos in raw:
        if pos - last >= 3:
            filtered.append(pos)
            last = pos

    return filtered


# -- zone computation ----------------------------------------------------------

def _zen_compute_zones(
    total_width: int,
    has_items: bool,
    has_queued: bool,
    vision_count: int,
) -> List[Tuple[str, int, int]]:
    """Zone allocation: ``(zone_name, width, start_col)`` tuples.

    Uses a 77% past zone when future zones exist.
    """
    usable = total_width - 4  # 4 chars for emoji prefix
    col = 4

    future_count = (1 if has_queued else 0) + vision_count

    if future_count > 1:
        past_width = usable * 77 // 100
        future_width = usable - past_width - 4  # 4 for present marker
    elif future_count == 1:
        future_width = 6
        past_width = usable - 4 - future_width
    else:
        past_width = usable - 4
        future_width = 0

    zones: List[Tuple[str, int, int]] = []

    if has_items:
        zones.append(("past", past_width, col))
        col += past_width

    zones.append(("present", 4, col))
    col += 4

    if future_count > 0:
        per_future = future_width // future_count if future_count > 0 else future_width
        remaining_future = future_width

        if has_queued:
            zones.append(("near", per_future, col))
            col += per_future
            remaining_future -= per_future
            future_count -= 1

        if vision_count > 0:
            per_vision = remaining_future // future_count if future_count > 0 else 0
            for idx in range(vision_count):
                if idx == 0:
                    vkey = "medium"
                elif idx == 1:
                    vkey = "long"
                elif idx == 2:
                    vkey = "vision"
                else:
                    vkey = f"vision_{idx + 1}"

                if idx == vision_count - 1:
                    zones.append((vkey, remaining_future, col))
                else:
                    zones.append((vkey, per_vision, col))
                    col += per_vision
                    remaining_future -= per_vision

    return zones


__all__ = [
    "_WIDTH",
    "_MAX_LABELS",
    "_STOP_WORDS",
    "_VISION_SECTIONS",
    "_zen_check_visibility",
    "_zen_query_projects",
    "_zen_project_id",
    "_zen_query_items",
    "_zen_queued_count",
    "_zen_compute_window",
    "_zen_item_positions",
    "_zen_compute_zones",
]
