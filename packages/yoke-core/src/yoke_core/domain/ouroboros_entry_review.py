"""Bounded review operations for the Ouroboros learning queue.

Every review batch runs against one named project. See
:mod:`yoke_core.domain.ouroboros_entry_write_scope` for the scoping rule
these selectors enforce.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import iso8601_now, query_rows, query_scalar
from yoke_core.domain.ouroboros_entries import MAX_ENTRY_LIST_LIMIT
from yoke_core.domain.ouroboros_entry_write_scope import (
    project_scope_predicate,
    require_bulk_scope_project_id,
)


MAX_ENTRY_REVIEW_BATCH = MAX_ENTRY_LIST_LIMIT


@dataclass(frozen=True)
class EntryReviewBatch:
    reviewed_count: int
    remaining_count: int
    reviewed_at: str | None


def normalize_entry_review_cutoff(value: str) -> str:
    """Require a date boundary whose lexical order matches stored UTC text."""
    text = str(value or "").strip()
    try:
        normalized = date.fromisoformat(text).isoformat()
    except ValueError as exc:
        raise ValueError("review cutoff must be an ISO date (YYYY-MM-DD)") from exc
    if normalized != text:
        raise ValueError("review cutoff must be an ISO date (YYYY-MM-DD)")
    return normalized


def mark_entries_reviewed_before(
    conn: Any,
    *,
    before: str,
    project: Optional[str],
    category_prefix: str | None = None,
    limit: int = MAX_ENTRY_REVIEW_BATCH,
    include_unattributed: bool = False,
) -> EntryReviewBatch:
    """Review a bounded set of one project's stale entries; report work remaining.

    ``project`` is required — a cutoff with no project would review every
    project's queue in one call. ``include_unattributed`` widens the batch
    to entries that belong to no project.
    """
    cutoff = normalize_entry_review_cutoff(before)
    if limit <= 0 or limit > MAX_ENTRY_REVIEW_BATCH:
        raise ValueError(f"limit must be between 1 and {MAX_ENTRY_REVIEW_BATCH}")
    project_id = require_bulk_scope_project_id(conn, project)
    project_sql, project_params = project_scope_predicate(
        conn,
        project_id,
        include_unattributed=include_unattributed,
    )

    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    category_predicate = f"category LIKE {p} AND " if category_prefix else ""
    predicate = (
        f"{category_predicate}{project_sql} AND created_at < {p} "
        "AND reviewed_at IS NULL AND archived_at IS NULL"
    )
    filter_params = (
        (f"{category_prefix}%", *project_params, cutoff)
        if category_prefix
        else (*project_params, cutoff)
    )
    rows = query_rows(
        conn,
        "SELECT id FROM ouroboros_entries "
        f"WHERE {predicate} ORDER BY created_at ASC, id ASC LIMIT {p}",
        (*filter_params, limit),
    )
    entry_ids = [int(row[0]) for row in rows]
    reviewed_at: str | None = None
    reviewed_count = 0
    if entry_ids:
        reviewed_at = iso8601_now()
        placeholders = ", ".join(p for _entry_id in entry_ids)
        cursor = conn.execute(
            f"UPDATE ouroboros_entries SET reviewed_at={p} "
            f"WHERE {project_sql} AND reviewed_at IS NULL "
            f"AND archived_at IS NULL AND id IN ({placeholders})",
            (reviewed_at, *project_params, *entry_ids),
        )
        reviewed_count = int(cursor.rowcount)
        if reviewed_count < 0:
            reviewed_count = len(entry_ids)
        conn.commit()

    remaining = query_scalar(
        conn,
        f"SELECT COUNT(*) FROM ouroboros_entries WHERE {predicate}",
        filter_params,
    )
    return EntryReviewBatch(
        reviewed_count=reviewed_count,
        remaining_count=int(remaining or 0),
        reviewed_at=reviewed_at,
    )


__all__ = [
    "EntryReviewBatch",
    "MAX_ENTRY_REVIEW_BATCH",
    "mark_entries_reviewed_before",
    "normalize_entry_review_cutoff",
]
