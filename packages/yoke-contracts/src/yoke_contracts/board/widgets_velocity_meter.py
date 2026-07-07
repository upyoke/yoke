"""120-day velocity meter (4-row sparkline grid).

Renders four 120-day sparklines: activity, code lines, issues done,
strategy lines. Activity/delivery rows read the ``item_activity_days``
rollup and ``item_status_transitions`` history; all git-derived data
flows through the unified per-commit cache in
:mod:`widgets_commit_cache`.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from yoke_contracts.board.config import BoardConfig
from yoke_contracts.project_contract.board_art import emoji as E
from yoke_contracts.board.board_db import BoardDBLike
from yoke_contracts.board.sql import day_text_expr, days_ago_text_expr
from yoke_contracts.board.widgets_activity import (
    _CHART,
    _activity_day_counts,
    _build_sparkline,
    _date_range,
    _project_filter,
    _resolve_repos,
)
from yoke_contracts.board.widgets_commit_cache import (
    commits_per_day,
    lines_per_day,
    strategy_lines_per_day,
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
    Requires ``repo_root`` for git-log-based effort/SML rows.

    Row order: activity, code lines, issues done, strategy lines.
    """
    days = 120
    dates = _date_range(days)
    pf_t = _project_filter(scope, "t")

    repos: List[str] = _resolve_repos(db, scope, repo_root) if repo_root else []

    # --- Row 1: Activity (unique items touched per day, 120d) ---
    # Sourced from item_activity_days (real domain mutations) plus
    # per-task touch days from the transition history — see the lifetime
    # activity widget for the rationale for not using items.updated_at.
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
    act_task_rows = db.query_quiet(act_task_sql)

    cutoff = dates[0] if dates else ""
    act_counts: Dict[str, int] = {
        day: count for day, count in _activity_day_counts(db, scope).items()
        if day >= cutoff
    }
    for row in act_task_rows:
        act_counts[row[0]] = act_counts.get(row[0], 0) + int(row[1])

    # All git-derived rows read from the unified per-commit cache; one
    # warm-cache lookup or one cold populate covers effort, SML, and the
    # commit-fallback contribution to row 1.
    effort_counts = lines_per_day(repos, days)
    sml_counts = strategy_lines_per_day(repos, days)
    for day, n in commits_per_day(repos, days).items():
        act_counts[day] = act_counts.get(day, 0) + n

    act_values = [act_counts.get(d, 0) for d in dates]
    act_spark = _build_sparkline(act_values)

    effort_values = [effort_counts.get(d, 0) for d in dates]
    effort_spark = _build_sparkline(effort_values)

    # --- Row 3: Delivery (transitions into done/passed) ---
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
    del_rows = db.query_quiet(del_sql)
    del_counts: Dict[str, int] = {}
    for row in del_rows:
        del_counts[row[0]] = del_counts.get(row[0], 0) + int(row[1])
    del_values = [del_counts.get(d, 0) for d in dates]
    del_spark = _build_sparkline(del_values)

    sml_values = [sml_counts.get(d, 0) for d in dates]
    sml_spark = _build_sparkline(sml_values)

    return [
        f"{_CHART} {act_spark} 120d activity",
        f"{_FLOPPY} {effort_spark} 120d code",
        f"{_PACKAGE} {del_spark} 120d issues",
        f"{_COMPASS} {sml_spark} 120d strategy",
    ]


def _parse_shortstat(output: str) -> int:
    """Parse ``git diff --shortstat`` output, returning total lines changed."""
    total = 0
    for part in output.split(","):
        part = part.strip()
        if "insertion" in part:
            try:
                total += int(part.split()[0])
            except (ValueError, IndexError):
                pass
        elif "deletion" in part:
            try:
                total += int(part.split()[0])
            except (ValueError, IndexError):
                pass
    return total
