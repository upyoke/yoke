"""Shared board/Overview momentum day series and streak facts.

One SQL definition for issues + strategy volume and one streak formula so
the terminal board and hosted Overview cannot diverge on the same scope.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional

UTC = timezone.utc


def _markers(values: list[int]) -> str:
    return ", ".join("%s" for _ in values)


def _utc_today() -> date:
    return datetime.now(UTC).date()


def strategy_bytes_by_day(
    conn: Any,
    project_ids: list[int],
    *,
    start_day: str,
) -> dict[str, int]:
    """SUM(new_bytes) per day from StrategyDocCreated / StrategyDocReplaced."""

    if not project_ids:
        return {}
    from yoke_core.domain.schema_common import _table_exists

    if not _table_exists(conn, "events"):
        return {}
    new_bytes = "(envelope::jsonb -> 'context' ->> 'new_bytes')::int"
    day = "SUBSTRING(created_at, 1, 10)"
    rows = conn.execute(
        f"SELECT {day} AS day, SUM(COALESCE({new_bytes}, 0)) AS n "
        "FROM events "
        f"WHERE project_id IN ({_markers(project_ids)}) "
        "AND event_name IN ('StrategyDocCreated', 'StrategyDocReplaced') "
        f"AND {day} >= %s "
        f"GROUP BY {day}",
        (*project_ids, start_day),
    ).fetchall()
    return {str(row["day"]): int(row["n"] or 0) for row in rows}


def issues_done_by_day(
    conn: Any,
    project_ids: list[int],
    *,
    start_day: str,
) -> dict[str, int]:
    """Unique terminal-success transitions per day (board issues meter)."""

    if not project_ids:
        return {}
    from yoke_core.domain.schema_common import _table_exists

    if not _table_exists(conn, "item_status_transitions"):
        return {}
    rows = conn.execute(
        "SELECT SUBSTRING(t.created_at, 1, 10) AS day, COUNT(*) AS total "
        "FROM item_status_transitions t "
        f"WHERE t.project_id IN ({_markers(project_ids)}) "
        "AND t.to_status IN ('done', 'passed') "
        "AND SUBSTRING(t.created_at, 1, 10) >= %s "
        "GROUP BY SUBSTRING(t.created_at, 1, 10)",
        (*project_ids, start_day),
    ).fetchall()
    return {str(row["day"]): int(row["total"] or 0) for row in rows}


def activity_units_by_day(
    conn: Any,
    project_ids: list[int],
    *,
    start_day: str,
) -> dict[str, int]:
    """Item activity-day units + task-touch days (board activity without commits)."""

    series: Counter[str] = Counter()
    if not project_ids:
        return {}
    from yoke_core.domain.schema_common import _table_exists

    markers = _markers(project_ids)
    params = (*project_ids, start_day)
    if _table_exists(conn, "item_activity_days"):
        for row in conn.execute(
            "SELECT day, COUNT(DISTINCT item_id) AS total "
            "FROM item_activity_days "
            f"WHERE project_id IN ({markers}) AND day >= %s "
            "GROUP BY day",
            params,
        ).fetchall():
            series[str(row["day"])] += int(row["total"])
    if _table_exists(conn, "item_status_transitions"):
        for row in conn.execute(
            "SELECT day, COUNT(*) AS total FROM ("
            "  SELECT SUBSTRING(t.created_at, 1, 10) AS day, "
            "         t.item_id AS item_id, t.task_num AS task_num "
            "  FROM item_status_transitions t "
            f"  WHERE t.project_id IN ({markers}) "
            "  AND t.task_num IS NOT NULL "
            "  AND SUBSTRING(t.created_at, 1, 10) >= %s "
            "  GROUP BY 1, 2, 3"
            ") touched GROUP BY day",
            params,
        ).fetchall():
            series[str(row["day"])] += int(row["total"])
    return dict(series)


def compute_streak(
    active_days: Iterable[str],
    *,
    lookback_days: int = 365,
    today: date | None = None,
) -> int:
    """Consecutive active days ending today or yesterday (board formula)."""

    active = set(active_days)
    current = today or _utc_today()
    streak = 0
    started = False
    for offset in range(lookback_days + 1):
        day = (current - timedelta(days=offset)).isoformat()
        if day in active:
            started = True
            streak += 1
        elif not started and offset <= 1:
            continue
        else:
            break
    return streak


def lifetime_activity_pct(
    active_days: Iterable[str],
    *,
    project_days: int,
) -> Optional[float]:
    """Lifetime active-day percentage capped at 100.00."""

    if project_days <= 0:
        return None
    active_count = len(set(active_days))
    pct = min((active_count * 10000 + project_days // 2) // project_days, 10000)
    return pct / 100.0


def project_age_days(conn: Any, project_ids: list[int]) -> int:
    """Days since earliest project created_at (1 when unknown)."""

    if not project_ids:
        return 0
    row = conn.execute(
        "SELECT MIN(SUBSTRING(created_at, 1, 10)) AS first_day "
        f"FROM projects WHERE id IN ({_markers(project_ids)})",
        tuple(project_ids),
    ).fetchone()
    first = str(row["first_day"] or "") if row else ""
    if not first:
        return 0
    try:
        first_date = date.fromisoformat(first)
    except ValueError:
        return 0
    return max((_utc_today() - first_date).days + 1, 1)


def build_momentum_series(
    conn: Any,
    project_ids: list[int],
    *,
    days: int,
    code_by_day: Mapping[str, int] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return (momentum rows, streak facts) for Overview / shared readers."""

    today = _utc_today()
    first = today - timedelta(days=days - 1)
    start = first.isoformat()
    from yoke_core.domain.project_code_days import commits_by_day, lines_by_day

    activity = activity_units_by_day(conn, project_ids, start_day=start)
    issues = issues_done_by_day(conn, project_ids, start_day=start)
    strategy = strategy_bytes_by_day(conn, project_ids, start_day=start)
    code = dict(code_by_day) if code_by_day is not None else lines_by_day(
        conn, project_ids, start_day=start,
    )
    commit_days = commits_by_day(conn, project_ids, start_day=start)
    # Union commit presence into activity for streak (board formula).
    active_for_streak = set(activity)
    active_for_streak.update(day for day, n in commit_days.items() if int(n) > 0)
    active_for_streak.update(day for day, n in code.items() if int(n) > 0)
    # Also treat any issues/strategy day as active for streak continuity with board
    # only when activity/commit would — board uses activity∪commits only.
    streak = compute_streak(active_for_streak, today=today)
    age = project_age_days(conn, project_ids)
    # Lifetime uses all-time activity days, not just the momentum window.
    all_activity = activity_units_by_day(conn, project_ids, start_day="0001-01-01")
    lifetime_days = set(all_activity)
    lifetime_days.update(
        day
        for day, n in commits_by_day(
            conn, project_ids, start_day="0001-01-01",
        ).items()
        if int(n) > 0
    )
    pct = lifetime_activity_pct(lifetime_days, project_days=age)
    momentum: list[dict[str, Any]] = []
    for offset in range(days):
        day = (first + timedelta(days=offset)).isoformat()
        momentum.append(
            {
                "day": day,
                "activity": int(activity.get(day, 0)),
                "code": int(code.get(day, 0)),
                "issues": int(issues.get(day, 0)),
                "strategy": int(strategy.get(day, 0)),
            }
        )
    streak_facts = {
        "streak_days": streak,
        "lifetime_pct": pct,
        "project_days": age,
    }
    return momentum, streak_facts


__all__ = [
    "activity_units_by_day",
    "build_momentum_series",
    "compute_streak",
    "issues_done_by_day",
    "lifetime_activity_pct",
    "project_age_days",
    "strategy_bytes_by_day",
]
