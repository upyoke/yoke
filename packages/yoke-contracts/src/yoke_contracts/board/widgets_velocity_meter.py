"""120-day velocity meter (4-row sparkline grid).

Renders four 120-day sparklines: activity, code lines, issues done,
strategy volume. All four series come from
:mod:`yoke_contracts.board.momentum_series` — the same definitions the
Overview momentum endpoint serves — so the terminal meter and the web
dashboard render one composition. Replay payloads recorded before the
shared-series cutover are served by the retained legacy query shapes.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from yoke_contracts.board.config import BoardConfig
from yoke_contracts.project_contract.board_art import emoji as E
from yoke_contracts.board.board_db import BoardDBLike
from yoke_contracts.board.momentum_series import (
    STRATEGY_EVENT_NAMES,
    activity_items_query,
    activity_units_by_day,
    issues_done_by_day,
    lines_changed_by_day,
    strategy_bytes_by_day,
)
from yoke_contracts.board.sql import day_text_expr, days_ago_text_expr
from yoke_contracts.board.widgets_activity import (
    _CHART,
    _activity_day_counts,
    _build_sparkline,
    _date_range,
    _project_filter,
)
from yoke_contracts.board.widgets_code_days import (
    _scope_project_ids,
    code_commits_by_day,
    code_lines_by_day,
)

# ---------------------------------------------------------------------------
# Velocity-meter-only emoji constants
# ---------------------------------------------------------------------------

_FLOPPY = E.VELOCITY_CODE
_PACKAGE = E.VELOCITY_DELIVERY
_COMPASS = E.VELOCITY_STRATEGY


# ---------------------------------------------------------------------------
# Velocity meter (120-day, 4 rows)
# ---------------------------------------------------------------------------


def render_velocity_meter(
    db: BoardDBLike, config: BoardConfig, scope: str, repo_root: Optional[str] = None
) -> Optional[List[str]]:
    """Render the 120-day velocity meter (4 sparkline rows).

    Returns a list of 4 lines, or ``None`` if disabled or no data.
    ``repo_root`` is retained for call-site compatibility; code meters
    read ``project_code_days`` rather than local git.

    Row order: activity, code lines, issues done, strategy lines.
    """
    del repo_root  # ingest-only; meters read the control-plane rollup
    days = 120
    dates = _date_range(days)

    project_ids = _scope_project_ids(db, scope)
    if project_ids and _payload_serves_shared_series(db, project_ids, days):
        act_counts = activity_units_by_day(db, project_ids, days=days)
        effort_counts = lines_changed_by_day(db, project_ids, days=days)
        del_counts = issues_done_by_day(db, project_ids, days=days)
        sml_counts = strategy_bytes_by_day(db, project_ids, days=days)
    else:
        act_counts, effort_counts, del_counts, sml_counts = _legacy_series(
            db, scope, days, dates
        )

    act_spark = _build_sparkline([act_counts.get(d, 0) for d in dates])
    effort_spark = _build_sparkline([effort_counts.get(d, 0) for d in dates])
    del_spark = _build_sparkline([del_counts.get(d, 0) for d in dates])
    sml_spark = _build_sparkline([sml_counts.get(d, 0) for d in dates])

    return [
        f"{_CHART} {act_spark} 120d activity",
        f"{_FLOPPY} {effort_spark} 120d code",
        f"{_PACKAGE} {del_spark} 120d issues",
        f"{_COMPASS} {sml_spark} 120d strategy",
    ]


def _payload_serves_shared_series(
    db: BoardDBLike, project_ids: List[int], days: int
) -> bool:
    """Replay payloads recorded before the shared-series cutover lack its queries."""
    has_query = getattr(db, "has_query", None)
    if not callable(has_query):
        return True
    return has_query(*activity_items_query(project_ids, days))


def _legacy_series(
    db: BoardDBLike, scope: str, days: int, dates: List[str]
) -> Tuple[Dict[str, int], Dict[str, int], Dict[str, int], Dict[str, int]]:
    """Serve the meter from the query shapes older payloads recorded."""
    pf_t, scope_params = _project_filter(scope, "t")

    transition_day = day_text_expr("t.created_at")
    act_task_sql = (
        "SELECT day, COUNT(*) AS cnt FROM ("
        f"  SELECT {transition_day} AS day,"
        "    COALESCE(CAST(t.project_id AS TEXT), '') AS project_id,"
        "    COALESCE(CAST(t.item_id AS TEXT), '') AS item_id,"
        "    COALESCE(CAST(t.task_num AS TEXT), '-') AS task_num"
        "  FROM item_status_transitions t"
        "  WHERE t.task_num IS NOT NULL"
        f"    AND t.created_at >= {days_ago_text_expr(days)} {pf_t}"
        "  GROUP BY day,"
        "    COALESCE(CAST(t.project_id AS TEXT), ''),"
        "    COALESCE(CAST(t.item_id AS TEXT), ''),"
        "    COALESCE(CAST(t.task_num AS TEXT), '-')"
        ") touched GROUP BY day ORDER BY day"
    )
    act_task_rows = db.query_quiet(act_task_sql, scope_params)

    cutoff = dates[0] if dates else ""
    act_counts: Dict[str, int] = {
        day: count
        for day, count in _activity_day_counts(db, scope).items()
        if day >= cutoff
    }
    for row in act_task_rows:
        act_counts[row[0]] = act_counts.get(row[0], 0) + int(row[1])

    effort_counts = code_lines_by_day(db, scope, days)
    sml_counts = _strategy_bytes_per_day(db, scope, days)
    for day, n in code_commits_by_day(db, scope, days).items():
        if n > 0:
            act_counts[day] = act_counts.get(day, 0) + n

    del_sql = (
        "SELECT day, COUNT(*) AS cnt FROM ("
        f"  SELECT {transition_day} AS day,"
        "    COALESCE(CAST(t.item_id AS TEXT), '') AS item_id,"
        "    COALESCE(CAST(t.task_num AS TEXT), '-') AS task_num"
        "  FROM item_status_transitions t"
        "  WHERE t.to_status IN ('done','passed')"
        f"    AND t.created_at >= {days_ago_text_expr(days)}"
        f"    {pf_t}"
        "  GROUP BY day,"
        "    COALESCE(CAST(t.item_id AS TEXT), ''),"
        "    COALESCE(CAST(t.task_num AS TEXT), '-')"
        ") grouped GROUP BY day ORDER BY day"
    )
    del_rows = db.query_quiet(del_sql, scope_params)
    del_counts: Dict[str, int] = {}
    for row in del_rows:
        del_counts[row[0]] = del_counts.get(row[0], 0) + int(row[1])

    return act_counts, effort_counts, del_counts, sml_counts


def _strategy_bytes_per_day(db: BoardDBLike, scope: str, days: int) -> Dict[str, int]:
    """Per-day strategy-doc authoring volume from the DB event stream."""
    day = day_text_expr("created_at")
    names = ", ".join(f"'{name}'" for name in STRATEGY_EVENT_NAMES)
    new_bytes = "(envelope::jsonb -> 'context' ->> 'new_bytes')::int"
    project_sql, params = _project_filter(scope, "")
    sql = (
        f"SELECT {day} AS day, SUM(COALESCE({new_bytes}, 0)) AS n "
        "FROM events "
        f"WHERE event_name IN ({names}) "
        f"AND created_at >= {days_ago_text_expr(days)}"
        f"{project_sql} "
        "GROUP BY day ORDER BY day"
    )
    counts: Dict[str, int] = {}
    for row in db.query_quiet(sql, params):
        if row and row[0] is not None:
            counts[str(row[0])] = int(row[1] or 0)
    return counts
