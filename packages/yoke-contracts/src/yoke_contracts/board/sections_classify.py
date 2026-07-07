"""Item classification for board sections.

Owns the project-scope SQL helper, the ``ItemRow`` row tuple, status and
priority helpers, the section bucket mapping, and the ``EpicStats`` /
``classify_items`` family used to translate raw item rows into the
section-keyed structure the renderer consumes.
"""

from __future__ import annotations

from typing import Dict, List, NamedTuple, Optional

from yoke_contracts.project_contract.board_art.emoji import STATUS_EMOJI as _STATUS_EMOJI_PREFIX
from yoke_contracts.board.board_db import BoardDBLike
from yoke_contracts.board.project_scope import project_filter, scope_project_id
from yoke_contracts.board.status import status_to_board_bucket
from yoke_contracts.lifecycle_status import TASK_TERMINAL_SUCCESS
from yoke_contracts.item_ref import format_item_ref

# ---------------------------------------------------------------------------
# Scope helper
# ---------------------------------------------------------------------------


def _project_filter_sql(
    scope: str,
    alias: str = "i",
    *,
    db: Optional[BoardDBLike] = None,
) -> str:
    """Return SQL AND clause fragment for project scoping.

    When *scope* is ``"all"``, returns the active authenticated visibility
    filter, or an empty string in local/admin context.
    Otherwise resolves the public slug/id through ``project_identity``
    and returns ``" AND <alias>.project_id = N"`` using the provided
    table alias prefix.
    """
    if scope == "all":
        return project_filter(scope, alias)
    project_id = _resolve_scope_project_id(scope, db=db)
    return f" AND {alias}.project_id = {project_id}"


def _resolve_scope_project_id(scope: str, *, db: Optional[BoardDBLike]) -> int:
    if str(scope).isdigit():
        return int(scope)
    if db is None:
        raise ValueError("board project scope resolution requires a database")
    return scope_project_id(db, scope)


# ---------------------------------------------------------------------------
# Named tuple for classified item rows
# ---------------------------------------------------------------------------

class ItemRow(NamedTuple):
    """A single classified backlog item row."""

    rank: int
    id: str  # Public item ref, e.g. "YOK-N".
    title: str
    type: str
    priority: str
    status: str
    progress: str
    epic_id: Optional[int]  # numeric epic_id (or None)
    worktree: str
    project: str
    updated_at: str


# ---------------------------------------------------------------------------
# Status emoji mapping
# ---------------------------------------------------------------------------

# Status glyphs are owned by yoke_contracts.project_contract.board_art.emoji.STATUS_EMOJI
# (imported above as _STATUS_EMOJI_PREFIX) — the canonical dedup registry.


def status_emoji(status: str, celebration: Optional[str] = None) -> str:
    """Map a status string to its emoji-prefixed display form.

    Returns ``"<emoji> <status>"`` for known statuses, or the raw status
    string for unrecognised values. When *celebration* is set and the status
    is ``done``, the celebration glyph replaces the normal ✅ (frontier
    inbox-zero flourish, kept consistent with the stats box and section header).
    """
    if celebration and status == "done":
        return f"{celebration} {status}"
    prefix = _STATUS_EMOJI_PREFIX.get(status)
    if prefix is None:
        return status
    return f"{prefix} {status}"


# ---------------------------------------------------------------------------
# Priority rank mapping
# ---------------------------------------------------------------------------

_PRIORITY_RANK: Dict[str, int] = {
    "critical": 1,
    "high": 2,
    "medium": 3,
    "low": 4,
}


def priority_rank(priority: str) -> int:
    """Map a priority string to a numeric sort key (lower = higher priority)."""
    return _PRIORITY_RANK.get(priority, 5)


# ---------------------------------------------------------------------------
# Section buckets
# ---------------------------------------------------------------------------

# Maps board-domain buckets to section names.
# Maps current board-domain buckets into rendered board sections.
# Blocked items render in their own section instead of being folded
# into Active. Blocked-flag rows (and any legacy status='blocked' drift)
# both end up in `_BUCKET_TO_SECTION["blocked"] == "blocked"`.
_BUCKET_TO_SECTION: Dict[str, str] = {
    "done": "done",
    "frozen": "freezer",
    "implementing": "active",
    "blocked": "blocked",
    "reviewing": "active",
    "implemented": "active",
    "release": "active",
    "planning": "pipeline",
    "refined": "pipeline",
    "idea": "backlog",
    "unknown": "unknown",
}


# ---------------------------------------------------------------------------
# Item classification
# ---------------------------------------------------------------------------


class EpicStats(NamedTuple):
    """Pre-computed epic statistics for batched board rendering."""

    task_count: int
    progress: str  # "N/M (PP%)" or "—"


def precompute_epic_stats(
    db: BoardDBLike,
    scope: str,
) -> Dict[int, EpicStats]:
    """Batch-query epic_id -> (task_count, progress) for all epics.

    Replaces both ``precompute_epic_task_counts`` and per-item
    ``epic_progress`` calls with a single SQL query.

    Args:
        db: Open database handle.
        scope: Project scope for filtering.

    Returns:
        Dict mapping epic_id to :class:`EpicStats`.
    """
    pf = _project_filter_sql(scope, db=db)
    _tts_in = ", ".join(f"'{s}'" for s in sorted(TASK_TERMINAL_SUCCESS))
    rows = db.query_quiet(
        f"""
        SELECT et.epic_id,
               COUNT(*) AS total,
               SUM(CASE WHEN et.status IN ({_tts_in}) THEN 1 ELSE 0 END) AS done
        FROM epic_tasks et
        JOIN items i ON i.id = et.epic_id
        WHERE 1=1{pf}
        GROUP BY et.epic_id
        """,
    )
    result: Dict[int, EpicStats] = {}
    for r in rows:
        epic_id = int(r[0])
        total = int(r[1])
        done = int(r[2] or 0)
        if total == 0:
            progress = "—"
        else:
            pct = done * 100 // total
            progress = f"{done}/{total} ({pct}%)"
        result[epic_id] = EpicStats(task_count=total, progress=progress)
    return result


def classify_items(
    db: BoardDBLike,
    scope: str,
    epic_stats: Optional[Dict[int, "EpicStats"]] = None,
) -> Dict[str, List[ItemRow]]:
    """Fetch all items and classify into board sections.

    Args:
        db: Open database handle.
        scope: Project scope string for filtering (e.g. ``"yoke"``).

    Returns:
        Dict mapping section names (``active``, ``pipeline``, ``backlog``,
        ``freezer``, ``done``, ``unknown``) to sorted lists of
        :class:`ItemRow`.
    """
    # Local import to avoid a load-time circular: ``sections_render`` imports
    # ``sections_classify`` for ``ItemRow``/``EpicStats``/``priority_rank``,
    # and ``classify_items`` only needs ``epic_progress`` as a fallback
    # when the caller did not provide ``epic_stats``.
    from yoke_contracts.board.sections_render import epic_progress

    sections: Dict[str, List[ItemRow]] = {
        "active": [],
        "pipeline": [],
        "backlog": [],
        "blocked": [],
        "freezer": [],
        "done": [],
        "unknown": [],
    }

    pf = _project_filter_sql(scope, db=db)
    sql = f"""
    SELECT
        i.id,
        REPLACE(i.title, '|', '∣'),
        COALESCE(i.type, 'issue'),
        COALESCE(i.status, 'idea'),
        COALESCE(i.priority, 'medium'),
        CASE WHEN i.frozen = 1 THEN 1 ELSE 0 END,
        CASE WHEN i.blocked = 1 THEN 1 ELSE 0 END,
        COALESCE(i.worktree, ''),
        i.id,
        CASE WHEN p.emoji IS NOT NULL AND p.emoji <> ''
             THEN p.emoji || ' ' || p.slug
             ELSE p.slug END,
        COALESCE(i.updated_at, ''),
        p.slug,
        p.public_item_prefix,
        i.project_sequence
    FROM items i
    LEFT JOIN projects p ON p.id = i.project_id
    WHERE 1=1{pf}
    ORDER BY i.id
    """
    rows = db.query(sql)

    for row in rows:
        (
            item_id_raw,
            title,
            item_type,
            status,
            priority,
            frozen_int,
            blocked_int,
            worktree,
            numid,
            project_display,
            updated_at,
            project_slug,
            public_item_prefix,
            project_sequence,
        ) = row
        yok_id = format_item_ref(
            project_slug,
            public_item_prefix,
            project_sequence,
            item_id=int(item_id_raw),
        )

        eff_epic: Optional[int] = int(numid) if item_type == "epic" else None

        # Compute progress — use precomputed stats when available
        if eff_epic is not None and epic_stats is not None:
            es = epic_stats.get(eff_epic)
            progress = es.progress if es is not None else "—"
        elif eff_epic is not None:
            progress = epic_progress(db, eff_epic)
        else:
            progress = "—"

        rank = priority_rank(priority)

        item_row = ItemRow(
            rank=rank,
            id=yok_id,
            title=title,
            type=item_type,
            priority=priority,
            status=status,
            progress=progress,
            epic_id=eff_epic,
            worktree=worktree,
            project=project_display,
            updated_at=updated_at,
        )

        # Classify using the domain bucket function
        bucket = status_to_board_bucket(
            status,
            frozen_value=frozen_int,
            blocked_value=blocked_int,
            item_type=item_type,
        )
        section = _BUCKET_TO_SECTION.get(bucket, "unknown")
        sections[section].append(item_row)

    # Sort active/pipeline/backlog/blocked/freezer by priority rank, then item id.
    for section_name in ("active", "pipeline", "backlog", "blocked", "freezer", "unknown"):
        sections[section_name].sort(key=lambda r: (r.rank, r.id))

    sections["done"].sort(key=lambda r: (r.updated_at, r.id), reverse=True)

    return sections
