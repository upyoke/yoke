"""Shared per-day momentum series for board and Overview surfaces.

One SQL definition per series — activity (items touched + task touches +
commits), issues delivered, strategy authoring volume, and code from the
``project_code_days`` rollup — parameterized by explicit project ids so the
terminal velocity meter and the Overview momentum endpoint cannot diverge
on composition. Date cutoffs live inside the SQL text
(:func:`days_ago_text_expr`), never in client-computed parameters, so board
record/replay keys stay stable across a midnight boundary; ``days=None``
means all-time.
"""

from __future__ import annotations

from collections import Counter
from typing import Dict, Optional, Sequence, Tuple

from yoke_contracts.board.board_db import BoardDBLike
from yoke_contracts.board.sql import day_text_expr, days_ago_text_expr

# Strategy-doc write events whose ``new_bytes`` payload is the per-day
# authoring-volume signal for the strategy series.
STRATEGY_EVENT_NAMES = ("StrategyDocCreated", "StrategyDocReplaced")


def _markers(project_ids: Sequence[int]) -> str:
    return ", ".join("%s" for _ in project_ids)


def _day_filter(column_sql: str, days: Optional[int]) -> str:
    if days is None:
        return ""
    return f" AND {column_sql} >= {days_ago_text_expr(int(days))}"


def activity_items_query(
    project_ids: Sequence[int], days: Optional[int],
) -> Tuple[str, Tuple]:
    """(sql, params) for the distinct-items activity component.

    Exposed so replay consumers can probe payload coverage with the exact
    query key before choosing this series over an older recorded shape.
    """

    sql = (
        "SELECT day, COUNT(DISTINCT item_id) AS total "
        "FROM item_activity_days "
        f"WHERE project_id IN ({_markers(project_ids)})"
        f"{_day_filter('day', days)} "
        "GROUP BY day"
    )
    return sql, tuple(project_ids)


def activity_units_by_day(
    db: BoardDBLike,
    project_ids: Sequence[int],
    *,
    days: Optional[int],
) -> Dict[str, int]:
    """Items touched + task-touch transitions + commits, summed per day.

    The commit component (``project_code_days.commit_count``) makes a
    code-only day register as activity with the same weight on every
    surface that renders this series.
    """

    if not project_ids:
        return {}
    series: Counter[str] = Counter()
    items_sql, params = activity_items_query(project_ids, days)
    for row in db.query(items_sql, params):
        if row and row[0]:
            series[str(row[0])] += int(row[1] or 0)
    transition_day = day_text_expr("t.created_at")
    for row in db.query(
        "SELECT day, COUNT(*) AS total FROM ("
        f"  SELECT {transition_day} AS day, t.item_id AS item_id, "
        "         t.task_num AS task_num "
        "  FROM item_status_transitions t "
        f"  WHERE t.project_id IN ({_markers(project_ids)}) "
        "  AND t.task_num IS NOT NULL"
        f"{_day_filter(transition_day, days)} "
        "  GROUP BY 1, 2, 3"
        ") touched GROUP BY day",
        params,
    ):
        if row and row[0]:
            series[str(row[0])] += int(row[1] or 0)
    for day, count in commit_count_by_day(db, project_ids, days=days).items():
        if count > 0:
            series[day] += count
    return dict(series)


def issues_done_by_day(
    db: BoardDBLike,
    project_ids: Sequence[int],
    *,
    days: Optional[int],
) -> Dict[str, int]:
    """Terminal-success transitions per day, one per (item, task)."""

    if not project_ids:
        return {}
    transition_day = day_text_expr("t.created_at")
    counts: Dict[str, int] = {}
    for row in db.query(
        "SELECT day, COUNT(*) AS total FROM ("
        f"  SELECT {transition_day} AS day, t.item_id AS item_id, "
        "         COALESCE(CAST(t.task_num AS TEXT), '-') AS task_num "
        "  FROM item_status_transitions t "
        f"  WHERE t.project_id IN ({_markers(project_ids)}) "
        "  AND t.to_status IN ('done', 'passed')"
        f"{_day_filter(transition_day, days)} "
        "  GROUP BY 1, 2, 3"
        ") delivered GROUP BY day",
        tuple(project_ids),
    ):
        if row and row[0]:
            counts[str(row[0])] = int(row[1] or 0)
    return counts


def strategy_bytes_by_day(
    db: BoardDBLike,
    project_ids: Sequence[int],
    *,
    days: Optional[int],
) -> Dict[str, int]:
    """SUM(new_bytes) per day from strategy-doc write events."""

    if not project_ids:
        return {}
    event_day = day_text_expr("created_at")
    new_bytes = "(envelope::jsonb -> 'context' ->> 'new_bytes')::int"
    names = ", ".join(f"'{name}'" for name in STRATEGY_EVENT_NAMES)
    counts: Dict[str, int] = {}
    for row in db.query(
        f"SELECT {event_day} AS day, SUM(COALESCE({new_bytes}, 0)) AS total "
        "FROM events "
        f"WHERE project_id IN ({_markers(project_ids)}) "
        f"AND event_name IN ({names})"
        f"{_day_filter(event_day, days)} "
        "GROUP BY 1",
        tuple(project_ids),
    ):
        if row and row[0]:
            counts[str(row[0])] = int(row[1] or 0)
    return counts


def _code_series(
    db: BoardDBLike,
    project_ids: Sequence[int],
    days: Optional[int],
    column: str,
) -> Dict[str, int]:
    if not project_ids:
        return {}
    counts: Dict[str, int] = {}
    for row in db.query(
        f"SELECT day, SUM({column}) AS total "
        "FROM project_code_days "
        f"WHERE project_id IN ({_markers(project_ids)})"
        f"{_day_filter('day', days)} "
        "GROUP BY day",
        tuple(project_ids),
    ):
        if row and row[0]:
            counts[str(row[0])] = int(row[1] or 0)
    return counts


def commit_count_by_day(
    db: BoardDBLike,
    project_ids: Sequence[int],
    *,
    days: Optional[int],
) -> Dict[str, int]:
    """Per-day SUM(commit_count) from ``project_code_days``."""

    return _code_series(db, project_ids, days, "commit_count")


def lines_changed_by_day(
    db: BoardDBLike,
    project_ids: Sequence[int],
    *,
    days: Optional[int],
) -> Dict[str, int]:
    """Per-day SUM(lines_changed) from ``project_code_days``."""

    return _code_series(db, project_ids, days, "lines_changed")


__all__ = [
    "STRATEGY_EVENT_NAMES",
    "activity_items_query",
    "activity_units_by_day",
    "commit_count_by_day",
    "issues_done_by_day",
    "lines_changed_by_day",
    "strategy_bytes_by_day",
]
