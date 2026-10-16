"""Database reads feeding the board item classifier."""

from __future__ import annotations

from typing import Dict, List, Optional

from yoke_contracts.board.board_db import BoardDBLike
from yoke_contracts.board.project_scope import project_filter
from yoke_contracts.board.sections_definition_queries import query_item_rows
from yoke_contracts.lifecycle_status import TASK_TERMINAL_SUCCESS
from yoke_contracts.board.item_data import (
    EpicStats,
    ItemRow,
    classify_item_rows,
    priority_rank,
    status_emoji,
)

_ITEM_FIELDS = (
    "item_id_raw",
    "title",
    "workflow_id",
    "status",
    "priority",
    "frozen_int",
    "blocked_int",
    "numid",
    "project_display",
    "updated_at",
    "project_slug",
    "public_item_prefix",
    "project_sequence",
    "status_glyph",
    "status_bucket",
    "merge_queue_enqueued_at",
    "merge_queue_landed_at",
    "generated_children",
)


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
    pf, params = project_filter(scope, "i")
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
        params,
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
    epic_stats: Optional[Dict[int, EpicStats]] = None,
) -> Dict[str, List[ItemRow]]:
    """Read scoped facts and classify them through the pure item projection."""
    if epic_stats is None:
        epic_stats = precompute_epic_stats(db, scope)
    pf, params = project_filter(scope, "i")
    rows = (
        dict(zip(_ITEM_FIELDS, row, strict=True))
        for row in query_item_rows(db, pf, params)
    )
    return classify_item_rows(rows, epic_stats)


__all__ = [
    "EpicStats",
    "ItemRow",
    "classify_items",
    "precompute_epic_stats",
    "priority_rank",
    "status_emoji",
]
