"""Idempotent field-note promotion into the Dash workflow."""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Any, Mapping, Optional

from yoke_contracts.item_ref import format_item_ref
from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.field_note_dash_promotion_reads import (
    promoted_dash_by_field_note_ids,
    source_field_note_for_dash,
)
from yoke_core.domain.field_note_dash_promotion_recovery import (
    find_unlinked_promoted_dash,
    persist_completed_promotion,
    release_promotion_reservation,
    try_hold_promotion_reservation,
)
from yoke_core.domain.schema_init_apply import execute_schema_script


class FieldNotePromotionError(RuntimeError):
    """A field note cannot be promoted with the supplied inputs."""


class FieldNotePromotionInProgress(FieldNotePromotionError):
    """Another caller already reserved this field note."""


@dataclass(frozen=True)
class FieldNotePromotion:
    entry_id: int
    dash_item_id: int
    dash_item_ref: str
    created: bool


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS ouroboros_entry_dispositions (
  entry_id INTEGER PRIMARY KEY REFERENCES ouroboros_entries(id),
  disposition_kind TEXT NOT NULL,
  state TEXT NOT NULL CHECK(state IN ('creating','completed','failed')),
  item_id INTEGER UNIQUE REFERENCES items(id),
  title TEXT NOT NULL,
  instruction TEXT NOT NULL,
  requested_by_actor_id INTEGER,
  requested_by_session_id TEXT,
  project_override TEXT,
  failure_reason TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ouroboros_entry_dispositions_item
  ON ouroboros_entry_dispositions(item_id);
"""


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _row_dict(cursor: Any) -> Optional[dict[str, Any]]:
    row = cursor.fetchone()
    if row is None:
        return None
    columns = [str(column[0]) for column in cursor.description]
    return dict(row) if hasattr(row, "keys") else dict(zip(columns, row))


def ensure_field_note_dash_promotion_schema(conn: Any) -> None:
    """Create the additive supporting-record disposition store."""
    execute_schema_script(conn, _SCHEMA_SQL)
    conn.commit()


def _promotion_row(conn: Any, entry_id: int) -> Optional[dict[str, Any]]:
    marker = _p(conn)
    return _row_dict(conn.execute(
        "SELECT d.entry_id, d.state, d.item_id AS dash_item_id, "
        "d.failure_reason, d.title, d.created_at, "
        "i.project_sequence, p.slug AS project_slug, "
        "p.public_item_prefix FROM ouroboros_entry_dispositions d "
        "LEFT JOIN items i ON i.id = d.item_id "
        "LEFT JOIN projects p ON p.id = i.project_id "
        f"WHERE d.entry_id = {marker} "
        f"AND d.disposition_kind = {marker}",
        (int(entry_id), "promote_to_dash"),
    ))


def _completed(row: dict[str, Any], *, created: bool) -> FieldNotePromotion:
    return FieldNotePromotion(
        entry_id=int(row["entry_id"]),
        dash_item_id=int(row["dash_item_id"]),
        dash_item_ref=format_item_ref(
            row["project_slug"],
            row["public_item_prefix"],
            row["project_sequence"],
            item_id=int(row["dash_item_id"]),
        ),
        created=created,
    )


def _field_note(conn: Any, entry_id: int) -> dict[str, Any]:
    marker = _p(conn)
    row = _row_dict(conn.execute(
        "SELECT o.id, o.category, o.body, o.project_id, "
        "p.slug AS project_slug, t.slug AS target_project_slug "
        "FROM ouroboros_entries o "
        "LEFT JOIN projects p ON p.id = o.project_id "
        "LEFT JOIN projects t ON t.id = o.target_project_id "
        f"WHERE o.id = {marker}",
        (int(entry_id),),
    ))
    if row is None:
        raise FieldNotePromotionError(f"field note {entry_id} does not exist")
    if not str(row["category"]).startswith("field-note-"):
        raise FieldNotePromotionError(
            f"ouroboros entry {entry_id} is not a field note"
        )
    return row


def _reserve(
    conn: Any,
    *,
    entry_id: int,
    title: str,
    instruction: str,
    actor_id: Optional[int],
    session_id: Optional[str],
    project_override: Optional[str] = None,
) -> bool:
    marker = _p(conn)
    now = iso8601_now()
    inserted = conn.execute(
        "INSERT INTO ouroboros_entry_dispositions "
        "(entry_id, disposition_kind, state, title, instruction, "
        "requested_by_actor_id, "
        "requested_by_session_id, project_override, created_at, updated_at) "
        f"VALUES ({', '.join(marker for _ in range(10))}) "
        "ON CONFLICT(entry_id) DO NOTHING RETURNING entry_id",
        (
            int(entry_id),
            "promote_to_dash",
            "creating",
            title,
            instruction,
            actor_id,
            session_id,
            project_override,
            now,
            now,
        ),
    ).fetchone()
    if inserted is not None:
        conn.commit()
        return True
    row = _promotion_row(conn, entry_id)
    if row and row["state"] == "failed":
        conn.execute(
            "UPDATE ouroboros_entry_dispositions "
            f"SET state = 'creating', title = {marker}, instruction = {marker}, "
            f"requested_by_actor_id = {marker}, "
            f"requested_by_session_id = {marker}, project_override = {marker}, "
            f"failure_reason = NULL, "
            f"updated_at = {marker} WHERE entry_id = {marker}",
            (
                title, instruction, actor_id, session_id, project_override,
                now, int(entry_id),
            ),
        )
        conn.commit()
        return True
    if row and row["state"] == "creating":
        conn.execute(
            "UPDATE ouroboros_entry_dispositions "
            f"SET requested_by_actor_id = {marker}, "
            f"requested_by_session_id = {marker}, "
            f"updated_at = {marker} WHERE entry_id = {marker}",
            (actor_id, session_id, now, int(entry_id)),
        )
        conn.commit()
        return True
    return False


def _mark_failed(conn: Any, entry_id: int, reason: str) -> None:
    marker = _p(conn)
    conn.execute(
        "UPDATE ouroboros_entry_dispositions "
        f"SET state = 'failed', failure_reason = {marker}, "
        f"updated_at = {marker} WHERE entry_id = {marker}",
        (reason, iso8601_now(), int(entry_id)),
    )
    conn.commit()


def _in_progress(entry_id: int) -> FieldNotePromotionInProgress:
    return FieldNotePromotionInProgress(
        f"field note {entry_id} promotion is already in progress"
    )


def _finish(
    conn: Any,
    entry_id: int,
    item_id: int,
    *,
    created: bool,
) -> FieldNotePromotion:
    persist_completed_promotion(conn, entry_id=entry_id, item_id=item_id)
    completed = _promotion_row(conn, entry_id)
    if completed is None:
        raise FieldNotePromotionError("promotion link was not persisted")
    return _completed(completed, created=created)


def promote_field_note_to_dash(
    conn: Any,
    *,
    entry_id: int,
    title: str,
    instruction: Optional[str],
    project: Optional[str],
    priority: Optional[str],
    workflow_posture: Optional[Mapping[str, Any]],
    actor_id: Optional[int],
    session_id: Optional[str],
) -> FieldNotePromotion:
    """Create one Dash and preserve its disposition link on repeat calls.

    A live concurrent promote holds a connection-scoped reservation lock.
    An abandoned creating row is recovered: an already-created Dash is
    linked, otherwise creation resumes. Completed repeats and explicit
    failed retries keep their existing behavior.
    """
    existing = _promotion_row(conn, entry_id)
    if existing and existing["state"] == "completed":
        return _completed(existing, created=False)
    note = _field_note(conn, entry_id)
    clean_title = str(title).strip()
    clean_instruction = str(instruction or note["body"]).strip()
    if not clean_title:
        raise FieldNotePromotionError("promotion title is required")
    if not clean_instruction:
        raise FieldNotePromotionError("promotion instruction is required")
    override = str(project).strip() if project else None
    declared_target = str(note.get("target_project_slug") or "").strip() or None
    observing_project = str(note.get("project_slug") or "").strip() or None
    selected_project = override or declared_target or observing_project
    if selected_project is None:
        raise FieldNotePromotionError(
            "field note has no project; pass the target project explicitly"
        )
    if not try_hold_promotion_reservation(conn, entry_id):
        current = _promotion_row(conn, entry_id)
        if current and current["state"] == "completed":
            return _completed(current, created=False)
        raise _in_progress(entry_id)
    try:
        existing = _promotion_row(conn, entry_id)
        if existing and existing["state"] == "completed":
            return _completed(existing, created=False)
        if not _reserve(
            conn,
            entry_id=entry_id,
            title=clean_title,
            instruction=clean_instruction,
            actor_id=actor_id,
            session_id=session_id,
            project_override=override,
        ):
            current = _promotion_row(conn, entry_id)
            if current and current["state"] == "completed":
                return _completed(current, created=False)
            raise _in_progress(entry_id)
        current = _promotion_row(conn, entry_id)
        if current is None:
            raise FieldNotePromotionError("promotion reservation was not persisted")
        linked_id = current.get("dash_item_id")
        if linked_id is not None:
            return _finish(conn, entry_id, int(linked_id), created=False)
        orphan_id = find_unlinked_promoted_dash(
            conn,
            title=str(current["title"]),
            created_at=str(current["created_at"]),
        )
        if orphan_id is not None:
            return _finish(conn, entry_id, orphan_id, created=False)
        from yoke_core.domain.backlog_create_op import execute_create
        result = execute_create(
            title=clean_title,
            workflow="dash",
            priority=priority,
            project=selected_project,
            source=str(actor_id) if actor_id is not None else None,
            session_id=session_id,
            entry_surface="promotion",
            instruction=clean_instruction,
            workflow_posture=workflow_posture,
            out=io.StringIO(),
        )
        if not result.get("success"):
            reason = str(result.get("error") or "Dash creation failed")
            _mark_failed(conn, entry_id, reason)
            raise FieldNotePromotionError(reason)
        return _finish(conn, entry_id, int(result["item_id"]), created=True)
    finally:
        release_promotion_reservation(conn, entry_id)


__all__ = [
    "FieldNotePromotion",
    "FieldNotePromotionError",
    "FieldNotePromotionInProgress",
    "ensure_field_note_dash_promotion_schema",
    "promoted_dash_by_field_note_ids",
    "promote_field_note_to_dash",
    "source_field_note_for_dash",
]
