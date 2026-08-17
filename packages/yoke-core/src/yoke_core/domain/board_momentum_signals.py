"""Board/Overview momentum — server-side wrapper over the shared series.

Series composition lives in :mod:`yoke_contracts.board.momentum_series` —
one SQL definition consumed by the terminal velocity meter and this
builder — so the two surfaces cannot diverge. The streak and lifetime
formulas here match the terminal board's: a day is active when the shared
activity series (items + task touches + commits) registers it.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Mapping, Optional

from yoke_contracts.board.momentum_series import (
    activity_units_by_day,
    issues_done_by_day,
    lines_changed_by_day,
    strategy_bytes_by_day,
)
from yoke_core.domain.board_zen_signals import ConnBoardDB


def _markers(values: list[int]) -> str:
    return ", ".join("%s" for _ in values)


def _utc_today() -> date:
    return datetime.now(timezone.utc).date()


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
    db = ConnBoardDB(conn)

    activity = activity_units_by_day(db, project_ids, days=days)
    issues = issues_done_by_day(db, project_ids, days=days)
    strategy = strategy_bytes_by_day(db, project_ids, days=days)
    code = dict(code_by_day) if code_by_day is not None else (
        lines_changed_by_day(db, project_ids, days=days)
    )
    # The activity series already carries commit days, so activity presence
    # IS the board streak formula (activity ∪ commits).
    active_for_streak = {day for day, n in activity.items() if int(n) > 0}
    streak = compute_streak(active_for_streak, today=today)
    age = project_age_days(conn, project_ids)
    # Lifetime uses all-time activity days, not just the momentum window.
    all_activity = activity_units_by_day(db, project_ids, days=None)
    lifetime_days = {day for day, n in all_activity.items() if int(n) > 0}
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
    "build_momentum_series",
    "compute_streak",
    "lifetime_activity_pct",
    "project_age_days",
]
