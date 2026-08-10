"""Bounded review operations for the global Ouroboros learning queue."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from yoke_contracts.field_note_text import CATEGORY_PREFIX
from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import iso8601_now, query_rows, query_scalar
from yoke_core.domain.ouroboros_entries import MAX_ENTRY_LIST_LIMIT


MAX_FIELD_NOTE_REVIEW_BATCH = MAX_ENTRY_LIST_LIMIT


@dataclass(frozen=True)
class FieldNoteReviewBatch:
    reviewed_count: int
    remaining_count: int
    reviewed_at: str | None


def normalize_field_note_review_cutoff(value: str) -> str:
    """Require a date boundary whose lexical order matches stored UTC text."""
    text = str(value or "").strip()
    try:
        normalized = date.fromisoformat(text).isoformat()
    except ValueError as exc:
        raise ValueError("field_notes_before must be an ISO date (YYYY-MM-DD)") from exc
    if normalized != text:
        raise ValueError("field_notes_before must be an ISO date (YYYY-MM-DD)")
    return normalized


def mark_field_notes_reviewed_before(
    conn: Any,
    *,
    before: str,
    limit: int = MAX_FIELD_NOTE_REVIEW_BATCH,
) -> FieldNoteReviewBatch:
    """Review at most ``limit`` stale field-notes and report work remaining."""
    cutoff = normalize_field_note_review_cutoff(before)
    if limit <= 0 or limit > MAX_FIELD_NOTE_REVIEW_BATCH:
        raise ValueError(f"limit must be between 1 and {MAX_FIELD_NOTE_REVIEW_BATCH}")

    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    predicate = (
        f"category LIKE {p} AND created_at < {p} "
        "AND reviewed_at IS NULL AND archived_at IS NULL"
    )
    filter_params = (f"{CATEGORY_PREFIX}%", cutoff)
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
    return FieldNoteReviewBatch(
        reviewed_count=reviewed_count,
        remaining_count=int(remaining or 0),
        reviewed_at=reviewed_at,
    )


__all__ = [
    "FieldNoteReviewBatch",
    "MAX_FIELD_NOTE_REVIEW_BATCH",
    "mark_field_notes_reviewed_before",
    "normalize_field_note_review_cutoff",
]
