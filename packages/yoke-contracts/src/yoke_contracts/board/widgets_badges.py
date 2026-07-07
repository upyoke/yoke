"""Badge-family widgets: age heatmap + type badges + achievement badges.

Owns the age heatmap palette, the proportional cell allocator, and the
achievement-streak helper.
"""

from __future__ import annotations

from datetime import date
from typing import List, Optional

from yoke_contracts.board.config import BoardConfig
from yoke_contracts.project_contract.board_art import emoji as E
from yoke_contracts.board.board_db import BoardDBLike
from yoke_contracts.board.sql import age_days_expr
from yoke_contracts.board.widgets_activity import _active_day_set, _project_filter

# ---------------------------------------------------------------------------
# Badge-family emoji constants
# ---------------------------------------------------------------------------

_CLOCK = E.BADGE_CLOCK
_TAG = E.BADGE_TYPE
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


def render_age_heatmap(db: BoardDBLike, config: BoardConfig, scope: str) -> Optional[str]:
    """Render the age heatmap bar with legend.

    Returns ``None`` if there are no active (non-done, non-frozen) items.
    """
    pf = _project_filter(scope)
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
    row = db.query_quiet(sql)
    if not row or not row[0]:
        return None

    r = row[0]
    fresh = int(r[0] or 0)
    week = int(r[1] or 0)
    biweek = int(r[2] or 0)
    month = int(r[3] or 0)
    ancient = int(r[4] or 0)
    total = int(r[5] or 0)

    if total == 0:
        return None

    # Allocate up to 20 cells proportionally
    max_cells = 20
    buckets = [
        ("fresh", fresh, _AGE_FRESH),
        ("week", week, _AGE_WEEK),
        ("biweek", biweek, _AGE_BIWEEK),
        ("month", month, _AGE_MONTH),
        ("ancient", ancient, _AGE_ANCIENT),
    ]

    cells = _allocate_proportional(
        [count for _, count, _ in buckets], total, max_cells
    )

    bar = ""
    for i, (_, _, emoji) in enumerate(buckets):
        bar += emoji * cells[i]

    return (
        f"{_CLOCK} {bar} age: "
        f"{_AGE_FRESH}<6h {_AGE_WEEK}<1d {_AGE_BIWEEK}<3d "
        f"{_AGE_MONTH}<1w {_AGE_ANCIENT}>1w"
    )


def _allocate_proportional(
    counts: List[int], total: int, max_cells: int
) -> List[int]:
    """Allocate cells proportionally with rounding.

    Non-zero counts get at least 1 cell. Excess is trimmed from the largest.
    """
    if total <= 0:
        return [0] * len(counts)

    half = total // 2
    cells = [((c * max_cells + half) // total) for c in counts]

    # Ensure at least 1 for non-zero
    for i, c in enumerate(counts):
        if c > 0 and cells[i] < 1:
            cells[i] = 1

    # Clamp: reduce largest bucket if over max_cells
    while sum(cells) > max_cells:
        largest_idx = 0
        largest_val = cells[0]
        for i in range(1, len(cells)):
            if cells[i] > largest_val:
                largest_val = cells[i]
                largest_idx = i
        cells[largest_idx] -= 1

    return cells


# ---------------------------------------------------------------------------
# Type badges
# ---------------------------------------------------------------------------


def render_type_badges(db: BoardDBLike, config: BoardConfig, scope: str) -> Optional[str]:
    """Render type distribution badges.

    Returns ``None`` if there are no active (non-done, non-frozen) items.
    """
    pf = _project_filter(scope)
    sql = (
        "SELECT type, COUNT(*) AS cnt FROM items"
        " WHERE status NOT IN ('done','cancelled')"
        "  AND (frozen IS NULL OR frozen <> 1)"
        f"  {pf}"
        " GROUP BY type ORDER BY COUNT(*) DESC"
    )
    rows = db.query_quiet(sql)
    if not rows:
        return None

    parts = []
    for row in rows:
        t = row[0]
        if not t:
            continue
        parts.append(f"{t}:{int(row[1])}")

    if not parts:
        return None

    return f"{_TAG} {' '.join(parts)}"


# ---------------------------------------------------------------------------
# Achievement badges
# ---------------------------------------------------------------------------


def render_achievement_badges(
    db: BoardDBLike, config: BoardConfig, scope: str, tex_done: int = 0
) -> Optional[str]:
    """Render achievement badges based on done count, streak, and DB heuristics.

    Parameters
    ----------
    tex_done : int
        Task-expanded done count from section-derived stats.

    Returns ``None`` if no badges earned.
    """
    badges: List[str] = []
    pf = _project_filter(scope)

    done = max(0, int(tex_done))

    # --- Milestone badges ---
    half_k = done // 500
    if half_k >= 20:
        k = done // 1000
        badges.append(f"{_MEDAL} {k}kdone")
    elif half_k >= 2:
        k = half_k // 2
        half = half_k % 2
        if half == 1:
            badges.append(f"{_MEDAL} {k}.5kdone")
        else:
            badges.append(f"{_MEDAL} {k}kdone")
    elif done >= 500:
        badges.append(f"{_MEDAL} 500done")
    elif done >= 100:
        badges.append(f"{_MEDAL} 100done")
    elif done >= 50:
        badges.append(f"{_MEDAL} 50done")

    # --- Streak badges ---
    streak = _compute_achievement_streak(db, scope)
    tier = _streak_tier(streak)
    if tier > 0:
        badges.append(f"{_TARGET} streak{tier}")

    # --- Zero-bugs badge ---
    bug_count = db.scalar(
        "SELECT COUNT(*) FROM items"
        " WHERE status NOT IN ('done','cancelled')"
        "  AND (frozen IS NULL OR frozen <> 1)"
        f"  AND LOWER(title) LIKE '%bug%' {pf}"
    )
    bug_count = int(bug_count or 0)
    if bug_count == 0:
        badges.append(f"{_SHIELD} zero-bugs")

    # --- Inbox-zero badge ---
    idea_count = db.scalar(
        "SELECT COUNT(*) FROM items"
        " WHERE status = 'idea'"
        "  AND (frozen IS NULL OR frozen <> 1)"
        f"  {pf}"
    )
    idea_count = int(idea_count or 0)
    if idea_count == 0:
        badges.append(f"{_MAILBOX} inbox-zero")

    if not badges:
        return None

    return "  ".join(badges)


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
