"""Bounded review operations for the global Ouroboros learning queue."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import iso8601_now, query_rows, query_scalar
from yoke_core.domain.ouroboros_entries import MAX_ENTRY_LIST_LIMIT


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
    category_prefix: str | None = None,
    limit: int = MAX_ENTRY_REVIEW_BATCH,
) -> EntryReviewBatch:
    """Review a bounded set of stale entries and report work remaining."""
    cutoff = normalize_entry_review_cutoff(before)
    if limit <= 0 or limit > MAX_ENTRY_REVIEW_BATCH:
        raise ValueError(f"limit must be between 1 and {MAX_ENTRY_REVIEW_BATCH}")

    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    category_predicate = f"category LIKE {p} AND " if category_prefix else ""
    predicate = (
        f"{category_predicate}created_at < {p} "
        "AND reviewed_at IS NULL AND archived_at IS NULL"
    )
    filter_params = (
        (f"{category_prefix}%", cutoff) if category_prefix else (cutoff,)
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
            "WHERE reviewed_at IS NULL AND archived_at IS NULL "
            f"AND id IN ({placeholders})",
            (reviewed_at, *entry_ids),
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
