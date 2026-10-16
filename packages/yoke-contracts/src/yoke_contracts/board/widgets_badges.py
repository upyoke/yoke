"""Badge-family widgets: age heatmap + workflow badges + achievement badges.

Owns the age heatmap palette, the proportional cell allocator, and the
achievement-streak helper.
"""

from __future__ import annotations

from datetime import date
from typing import List

from yoke_contracts.board.widget_data import _allocate_proportional  # noqa: F401
from yoke_contracts.board.config import BoardConfig
from yoke_contracts.project_contract.board_art import emoji as E
from yoke_contracts.board.board_db import BoardDBLike
from yoke_contracts.board.sql import age_days_expr
from yoke_contracts.board.widgets_activity import _active_day_set, _project_filter

# ---------------------------------------------------------------------------
# Badge-family emoji constants
# ---------------------------------------------------------------------------

_CLOCK = E.BADGE_CLOCK
_TAG = E.BADGE_WORKFLOW
_MEDAL = E.BADGE_MILESTONE
_TARGET = E.BADGE_STREAK
_SHIELD = E.BADGE_ZERO_BUGS
_MAILBOX = E.BADGE_INBOX_ZERO

# Age heatmap colors
_AGE_FRESH = E.AGE_FRESH
_AGE_WEEK = E.AGE_WEEK
_AGE_BIWEEK = E.AGE_BIWEEK
_AGE_MONTH = E.AGE_MONTH
_AGE_ANCIENT = E.AGE_ANCIENT


# ---------------------------------------------------------------------------
# Age heatmap
# ---------------------------------------------------------------------------


def collect_age_counts(db: BoardDBLike, config: BoardConfig, scope: str) -> dict | None:
    """Render the age heatmap bar with legend.

    Returns ``None`` if there are no active (non-done, non-frozen) items.
    """
    pf, params = _project_filter(scope)
    sql = (
        "WITH aged AS ("
        f"  SELECT {age_days_expr('created_at')} AS age_days"
        "  FROM items"
        "  WHERE status NOT IN ('done','cancelled')"
        "    AND (frozen IS NULL OR frozen <> 1)"
        f"    {pf}"
        ") "
        "SELECT"
        "  SUM(CASE WHEN age_days < 6.0/24 THEN 1 ELSE 0 END) AS fresh,"
        "  SUM(CASE WHEN age_days >= 6.0/24 AND age_days < 1 THEN 1 ELSE 0 END) AS week,"
        "  SUM(CASE WHEN age_days >= 1 AND age_days < 3 THEN 1 ELSE 0 END) AS biweek,"
        "  SUM(CASE WHEN age_days >= 3 AND age_days < 7 THEN 1 ELSE 0 END) AS month,"
        "  SUM(CASE WHEN age_days >= 7 THEN 1 ELSE 0 END) AS ancient,"
        "  COUNT(*) AS total"
        " FROM aged"
    )
    row = db.query_quiet(sql, params)
    if not row or not row[0]:
        return None

    return dict(
        zip(
            ("fresh", "week", "biweek", "month", "ancient", "total"),
            [int(value or 0) for value in row[0]],
            strict=True,
        )
    )


# ---------------------------------------------------------------------------
# Workflow badges
# ---------------------------------------------------------------------------


def collect_workflow_counts(
    db: BoardDBLike,
    config: BoardConfig,
    scope: str,
) -> list:
    """Render workflow distribution badges.

    Returns ``None`` if there are no active (non-done, non-frozen) items.
    """
    pf, params = _project_filter(scope)
    sql = (
        "SELECT workflow_id, COUNT(*) AS cnt FROM items"
        " WHERE status NOT IN ('done','cancelled')"
        "  AND (frozen IS NULL OR frozen <> 1)"
        f"  {pf}"
        " GROUP BY workflow_id ORDER BY COUNT(*) DESC"
    )
    rows = db.query_quiet(sql, params)
    return rows


# ---------------------------------------------------------------------------
# Achievement badges
# ---------------------------------------------------------------------------


def collect_achievement_counts(
    db: BoardDBLike, config: BoardConfig, scope: str, tex_done: int = 0
) -> dict:
    """Collect achievement counts and render their earned badges."""
    pf, params = _project_filter(scope)
    streak = _compute_achievement_streak(db, scope)
    bug_count = db.scalar(
        "SELECT COUNT(*) FROM items"
        " WHERE status NOT IN ('done','cancelled')"
        "  AND (frozen IS NULL OR frozen <> 1)"
        f"  AND POSITION('bug' IN LOWER(title)) > 0 {pf}",
        params,
    )
    bug_count = int(bug_count or 0)
    idea_count = db.scalar(
        "SELECT COUNT(*) FROM items"
        " WHERE status = 'idea'"
        "  AND (frozen IS NULL OR frozen <> 1)"
        f"  {pf}",
        params,
    )
    idea_count = int(idea_count or 0)
    return dict(
        done=tex_done, streak=streak, bug_count=bug_count, idea_count=idea_count
    )


def _streak_tier(streak: int) -> int:
    """Snap *streak* down to its achievement tier.

    Tiers: 1, 5, 10, 20, 30, … 100, 200, 300, … Returns 0 below tier 1
    so the caller can suppress the badge entirely.
    """
    if streak < 1:
        return 0
    if streak < 5:
        return 1
    if streak < 10:
        return 5
    if streak < 100:
        return (streak // 10) * 10
    return (streak // 100) * 100


def _compute_achievement_streak(db: BoardDBLike, scope: str) -> int:
    """Compute longest historical activity streak for achievement badges.

    Day source is :func:`_active_day_set` (events ∪ commit-days), so the
    badge agrees with the sparkline on what counts as an active day.
    Returns the longest run of consecutive active days in the last 365.
    """
    active_days = _active_day_set(db, scope, 365)
    if not active_days:
        return 0

    sorted_days: List[date] = []
    for day_str in sorted(active_days):
        try:
            sorted_days.append(date.fromisoformat(day_str))
        except (ValueError, TypeError):
            continue

    if not sorted_days:
        return 0

    best = 1
    current_run = 1
    for i in range(1, len(sorted_days)):
        if (sorted_days[i] - sorted_days[i - 1]).days == 1:
            current_run += 1
        else:
            current_run = 1
        if current_run > best:
            best = current_run

    return best


def render_age_heatmap(db, config, scope):
    from yoke_contracts.board.widget_data import render_age_counts

    counts = collect_age_counts(db, config, scope)
    return render_age_counts(counts) if counts is not None else None


def render_workflow_badges(db, config, scope):
    from yoke_contracts.board.widget_data import render_workflow_counts

    return render_workflow_counts(collect_workflow_counts(db, config, scope))


def render_achievement_badges(db, config, scope, tex_done=0):
    from yoke_contracts.board.widget_data import render_achievement_counts

    return render_achievement_counts(
        **collect_achievement_counts(db, config, scope, tex_done)
    )
