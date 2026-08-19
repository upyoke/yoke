"""Bidirectional read projections for field-note Dash promotions."""

from __future__ import annotations

from typing import Any, Iterable, Optional

from yoke_contracts.item_ref import format_item_ref
from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _table_exists


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _row_dict(cursor: Any) -> Optional[dict[str, Any]]:
    row = cursor.fetchone()
    if row is None:
        return None
    columns = [str(column[0]) for column in cursor.description]
    return dict(row) if hasattr(row, "keys") else dict(zip(columns, row))


def _rows_dict(cursor: Any) -> list[dict[str, Any]]:
    columns = [str(column[0]) for column in cursor.description]
    return [
        dict(row) if hasattr(row, "keys") else dict(zip(columns, row))
        for row in cursor.fetchall()
    ]


def promoted_dash_by_field_note_ids(
    conn: Any,
    entry_ids: Iterable[int],
) -> dict[int, dict[str, Any]]:
    """Completed Dash promotion projected by its source field-note id."""
    ids = sorted({int(entry_id) for entry_id in entry_ids})
    if not ids or not _table_exists(conn, "ouroboros_entry_dispositions"):
        return {}
    marker = _p(conn)
    rows = _rows_dict(conn.execute(
        "SELECT d.entry_id, d.item_id AS dash_item_id, d.title, "
        "d.instruction, d.updated_at AS promoted_at, "
        "i.project_sequence, p.id AS project_id, p.slug AS project_slug, "
        "p.public_item_prefix "
        "FROM ouroboros_entry_dispositions d "
        "JOIN items i ON i.id = d.item_id "
        "JOIN projects p ON p.id = i.project_id "
        f"WHERE d.entry_id IN ({', '.join(marker for _ in ids)}) "
        f"AND d.disposition_kind = {marker} AND d.state = {marker}",
        (*ids, "promote_to_dash", "completed"),
    ))
    return {
        int(row["entry_id"]): {
            "item_id": int(row["dash_item_id"]),
            "item_ref": format_item_ref(
                row["project_slug"],
                row["public_item_prefix"],
                int(row["project_sequence"]),
            ),
            "project_id": int(row["project_id"]),
            "project": str(row["project_slug"]),
            "title": str(row["title"]),
            "instruction": str(row["instruction"]),
            "promoted_at": row.get("promoted_at"),
        }
        for row in rows
    }


def source_field_note_for_dash(
    conn: Any,
    item_id: int,
) -> Optional[dict[str, Any]]:
    """Source field note projected onto its completed promoted Dash."""
    if not _table_exists(conn, "ouroboros_entry_dispositions"):
        return None
    marker = _p(conn)
    row = _row_dict(conn.execute(
        "SELECT o.id AS entry_id, o.timestamp, o.agent, "
        "COALESCE(o.context, '') AS context, o.category, o.body, "
        "COALESCE(o.reviewed_at, '') AS reviewed_at, "
        "d.updated_at AS promoted_at, p.id AS project_id, "
        "COALESCE(p.slug, '') AS project "
        "FROM ouroboros_entry_dispositions d "
        "JOIN ouroboros_entries o ON o.id = d.entry_id "
        "LEFT JOIN projects p ON p.id = o.project_id "
        f"WHERE d.item_id = {marker} AND d.disposition_kind = {marker} "
        f"AND d.state = {marker}",
        (int(item_id), "promote_to_dash", "completed"),
    ))
    if row is None:
        return None
    return {
        "entry_id": int(row["entry_id"]),
        "timestamp": str(row["timestamp"]),
        "agent": str(row["agent"]),
        "context": str(row["context"]),
        "category": str(row["category"]),
        "body": str(row["body"]),
        "reviewed_at": str(row["reviewed_at"]),
        "promoted_at": row.get("promoted_at"),
        "project_id": (
            int(row["project_id"]) if row.get("project_id") is not None else None
        ),
        "project": str(row["project"]),
    }


__all__ = [
    "promoted_dash_by_field_note_ids",
    "source_field_note_for_dash",
]
