"""Activity-family widgets: weather + 14-day velocity sparkline.

Hosts the shared helpers (sparkline encoding, scoped project filter,
date-range builder, day-count merger) that the velocity-meter and
badges submodules import. Also owns the small set of emoji constants
used across more than one widget submodule (``_CHART``, ``_FIRE``).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

UTC = timezone.utc  # datetime.UTC is Python 3.11+; this alias also works on 3.10

from yoke_contracts.board.config import BoardConfig
from yoke_contracts.board.activity_cache import activity_day_counts
from yoke_contracts.board.board_db import BoardDBLike
from yoke_contracts.board.project_scope import (
    project_id_filter,
    project_filter as _project_filter,
    project_ref_where,
    visible_project_ids,
)
from yoke_contracts.board.sql import (
    day_from_timestamp_expr,
    timestamp_expr,
)
from yoke_contracts.board.widgets_commit_cache import (
    commits_per_day as _commits_per_day,
)
from yoke_contracts.machine_config import runtime as machine_config
from yoke_contracts.machine_config.schema import normalize_project_id

# ---------------------------------------------------------------------------
# Sparkline block characters (level 0-5)
# ---------------------------------------------------------------------------

_BLOCKS = "\u2581\u2582\u2583\u2585\u2587\u2588"  # ▁▂▃▅▇█

# ---------------------------------------------------------------------------
# Emoji constants shared across submodules
# ---------------------------------------------------------------------------

_CHART = "\U0001f4ca"  # 📊 (used by sparkline + velocity meter)
_FIRE = "\U0001f525"   # 🔥 (used by sparkline streak indicator)


def _utc_today() -> date:
    """The board's day vocabulary is UTC — `item_activity_days.day` and the
    transition timestamps are UTC dates, so window math on the LOCAL date
    drops today's rows every evening west of Greenwich."""
    return datetime.now(UTC).date()


def _date_range(days: int) -> List[str]:
    """Return a list of YYYY-MM-DD strings for the last *days* days (oldest first)."""
    today = _utc_today()
    return [(today - timedelta(days=d)).isoformat() for d in range(days - 1, -1, -1)]


def _merge_counts(day_counts: Dict[str, int], date_list: List[str]) -> List[Tuple[str, int]]:
    """Map a date list to counts, filling missing days with 0."""
    return [(d, day_counts.get(d, 0)) for d in date_list]


def _activity_day_counts(db: BoardDBLike, scope: str) -> Dict[str, int]:
    """Return activity-event touched-item counts by day for the rendered scope."""
    cache = getattr(db, "_activity_day_counts_cache", None)
    if cache is None:
        cache = {}
        setattr(db, "_activity_day_counts_cache", cache)
    key = _activity_cache_key(scope)
    if key in cache:
        return dict(cache[key])

    counts = activity_day_counts(db, scope)
    cache[key] = counts
    return dict(counts)


def _activity_cache_key(scope: str) -> str:
    ids = visible_project_ids()
    if ids is None:
        return scope
    return f"{scope}|visible:{','.join(str(project_id) for project_id in ids)}"


def _resolve_repos(
    db: BoardDBLike, scope: str, repo_root: Optional[str] = None
) -> List[str]:
    """Resolve local checkout paths for the projects a scope covers."""
    mapped = _mapped_checkouts(machine_config.load_config())
    if scope == "all":
        visibility = project_id_filter()
        rows = db.query_quiet(f"SELECT id FROM projects WHERE 1=1{visibility}")
        repos = [
            mapped[int(r[0])] for r in rows
            if r and int(r[0]) in mapped
        ]
        if repos:
            return repos
        return [repo_root] if repo_root else []
    where, params = project_ref_where(scope)
    rows = db.query_quiet(f"SELECT id FROM projects WHERE {where}", params)
    if rows and rows[0] and int(rows[0][0]) in mapped:
        return [mapped[int(rows[0][0])]]
    return [repo_root] if repo_root else []


def _mapped_checkouts(config: dict) -> Dict[int, str]:
    projects = config.get("projects", {})
    out: Dict[int, str] = {}
    if not isinstance(projects, dict):
        return out
    for checkout, entry in sorted(projects.items()):
        if not isinstance(entry, dict):
            continue
        project_id = normalize_project_id(entry.get("project_id"))
        if project_id is None:
            continue
        path = Path(str(checkout)).expanduser()
        if path.is_dir():
            out[int(project_id)] = str(path)
    return out


def _project_age_days(db: BoardDBLike, scope: str) -> Tuple[Optional[str], int]:
    """Return ``(first_iso, project_days)`` for *scope*'s project age."""
    pf = _project_filter(scope)
    first_day = day_from_timestamp_expr(f"MIN({timestamp_expr('created_at')})")
    first = db.scalar(
        f"SELECT {first_day} FROM items WHERE 1=1 {pf}"
    )
    if not first:
        return None, 0
    try:
        first_date = date.fromisoformat(str(first))
    except (ValueError, TypeError):
        return None, 0
    return first_date.isoformat(), (_utc_today() - first_date).days + 1


def _build_sparkline(values: List[int]) -> str:
    """Build a sparkline string from a list of integer values.

    Level 0 (no activity) uses the baseline block (index 0).
    Levels 1-5 scale linearly from index 1-5.
    """
    max_val = max(values) if values else 0
    chars = []
    for v in values:
        if v == 0 or max_val == 0:
            chars.append(_BLOCKS[0])
        else:
            # ceil(v / max * 5), clamped [1, 5]
            level = (v * 5 + max_val - 1) // max_val
            level = max(1, min(5, level))
            chars.append(_BLOCKS[level])
    return "".join(chars)


# ---------------------------------------------------------------------------
# Weather
# ---------------------------------------------------------------------------


def render_weather(db: BoardDBLike, config: BoardConfig, scope: str) -> str:
    """Render weather indicator based on unfrozen idea-status item count.

    Always produces output (never returns None).
    """
    pf = _project_filter(scope)
    sql = (
        "SELECT COUNT(*) FROM items "
        "WHERE status='idea' AND (frozen IS NULL OR frozen <> 1) "
        f"{pf}"
    )
    backlog = db.scalar(sql) or 0
    backlog = int(backlog)

    if backlog < 10:
        return "🌞 Clear"   # sun (Clear)
    elif backlog < 25:
        return "\u26c5 Fair"           # ⛅ Fair
    else:
        return "☔ Stormy"   # umbrella (Stormy)


# ---------------------------------------------------------------------------
# Velocity sparkline (14-day)
# ---------------------------------------------------------------------------


def render_velocity_sparkline(
    db: BoardDBLike,
    config: BoardConfig,
    scope: str,
    repo_root: Optional[str] = None,
) -> Optional[str]:
    """Render the 14-day velocity sparkline with streak indicator.

    Returns ``None`` if the sparkline is empty.

    Activity is counted from the ``item_activity_days`` rollup
    (see :mod:`yoke_core.domain.item_activity`); per-day commit
    counts are unioned in so days that produced code without a
    ticket-scoped mutation still register.
    """
    dates = _date_range(14)

    # Unique items touched per day (each item at most once per day),
    # sourced from the canonical activity event set.
    cutoff = (_utc_today() - timedelta(days=14)).isoformat()
    day_counts: Dict[str, int] = {
        day: count for day, count in _activity_day_counts(db, scope).items()
        if day >= cutoff
    }

    # One git-log call covers the 14d bar, the 365d streak, and the
    # lifetime percentage — fetch at the widest window any consumer needs.
    repos = _resolve_repos(db, scope, repo_root)
    first_iso, project_days = _project_age_days(db, scope)
    commits = _commits_per_day(repos, max(365, project_days))
    for day, n in commits.items():
        day_counts[day] = day_counts.get(day, 0) + n

    merged = _merge_counts(day_counts, dates)
    values = [c for _, c in merged]

    sparkline = _build_sparkline(values)

    streak = _compute_streak(db, scope, 365, commits=commits)

    output = f"{_CHART} {sparkline} 14d activity"

    if streak > 0:
        fire_cap = min(streak, 14)
        fires = _FIRE * fire_cap
        active_days, project_days = _compute_lifetime_activity(
            db, scope, commits=commits, project_age=(first_iso, project_days),
        )
        if project_days > 0:
            # Cap at 100%: active_days can exceed project_days (append-only
            # events survive deletion; backdated seeds predate the anchor).
            pct = min((active_days * 10000 + project_days // 2) // project_days, 10000)
            lifetime = f" ({pct // 100}.{pct % 100:02d}%)"
        else:
            lifetime = ""
        output = f"{output} | {fires} {streak}d streak{lifetime}"

    return output


def _active_day_set(
    db: BoardDBLike,
    scope: str,
    lookback_days: int,
    repo_root: Optional[str] = None,
    commits: Optional[Dict[str, int]] = None,
) -> set:
    """Return the set of YYYY-MM-DD strings active in the last *lookback_days*.

    A day is active if it has at least one ``item_activity_days`` row
    OR at least one commit in the scope's repos. *commits* may be a pre-fetched dict (from the
    dashboard's shared call) — when omitted the helper fetches its own.

    Shared by :func:`_compute_streak` (current run from today) and
    :func:`_compute_achievement_streak` (longest run anywhere in the
    window) so both metrics agree on what counts as an active day.
    """
    cutoff = (_utc_today() - timedelta(days=lookback_days)).isoformat()
    active_days: set = {
        day for day in _activity_day_counts(db, scope)
        if day >= cutoff
    }

    if commits is None:
        commits = _commits_per_day(_resolve_repos(db, scope, repo_root), lookback_days)
    active_days.update(commits.keys())

    return active_days


def _compute_streak(
    db: BoardDBLike,
    scope: str,
    lookback_days: int,
    repo_root: Optional[str] = None,
    commits: Optional[Dict[str, int]] = None,
) -> int:
    """Compute consecutive-day activity streak ending today or yesterday.

    Returns the streak count (0 if no recent activity). Day source is
    :func:`_active_day_set` (events ∪ commit-days).
    """
    active_days = _active_day_set(db, scope, lookback_days, repo_root, commits)

    # Walk backward from today counting consecutive active days
    today = _utc_today()
    streak = 0
    started = False

    for offset in range(lookback_days + 1):
        d = (today - timedelta(days=offset)).isoformat()
        if d in active_days:
            started = True
            streak += 1
        elif not started and offset <= 1:
            # Today might be 0, check yesterday
            continue
        else:
            break

    return streak


def _compute_lifetime_activity(
    db: BoardDBLike,
    scope: str,
    repo_root: Optional[str] = None,
    commits: Optional[Dict[str, int]] = None,
    project_age: Optional[Tuple[Optional[str], int]] = None,
) -> "tuple[int, int]":
    """Count distinct active days and total project days since first item.

    Returns ``(active_days, project_days)``. Events are the primary
    signal; commit days within the project's lifetime are unioned in
    so commit-only days still count. *commits* and *project_age* may
    be pre-fetched (from the dashboard's shared call); when omitted
    the helper fetches its own.
    """
    active_set: set = set(_activity_day_counts(db, scope))

    # Project age sourced from items.created_at — start date is
    # immutable as long as at least one original item remains. If the
    # very first items have been deleted this undercounts the age,
    # which biases the percentage up (conservative).
    if project_age is None:
        first_iso, project_days = _project_age_days(db, scope)
    else:
        first_iso, project_days = project_age

    if project_days > 0 and first_iso:
        if commits is None:
            commits = _commits_per_day(
                _resolve_repos(db, scope, repo_root), project_days,
            )
        # Clamp commit days to the project's own lifetime so a repo
        # whose history predates the first ticket can't push the
        # percentage above 100%.
        for day in commits:
            if day >= first_iso:
                active_set.add(day)

    return len(active_set), project_days
