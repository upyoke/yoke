"""Unified work-item roster with public references and live claim holders."""

from __future__ import annotations

from typing import Any, Iterable

from yoke_contracts.item_ref import format_item_ref
from yoke_core.domain import db_backend, db_helpers
from yoke_core.domain.item_page_claims import active_item_claims


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _dict_rows(cursor: Any) -> list[dict[str, Any]]:
    columns = [str(column[0]) for column in cursor.description]
    return [
        dict(row) if hasattr(row, "keys") else dict(zip(columns, row))
        for row in cursor.fetchall()
    ]


def enrich_item_overview_rows(
    rows: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Add stored owner, public reference, and active-claim facts."""
    base_rows = [dict(row) for row in rows]
    ids = [int(row["id"]) for row in base_rows]
    if not ids:
        return []
    conn = db_helpers.connect()
    try:
        marker = _p(conn)
        placeholders = ", ".join(marker for _ in ids)
        cursor = conn.execute(
            "SELECT i.id, i.owner, i.project_sequence, p.id AS project_id, "
            "p.slug AS project, p.name AS project_name, "
            "p.public_item_prefix "
            "FROM items i JOIN projects p ON p.id = i.project_id "
            f"WHERE i.id IN ({placeholders})",
            tuple(ids),
        )
        facts = {int(row["id"]): row for row in _dict_rows(cursor)}
        claims = active_item_claims(conn, ids)
    finally:
        conn.close()

    result: list[dict[str, Any]] = []
    for row in base_rows:
        item_id = int(row["id"])
        fact = facts[item_id]
        row.update({
            "public_ref": format_item_ref(
                fact["project"],
                fact["public_item_prefix"],
                fact["project_sequence"],
                item_id=item_id,
            ),
            "project_id": int(fact["project_id"]),
            "project": str(fact["project"]),
            "project_name": str(fact["project_name"]),
            "owner": str(fact.get("owner") or ""),
            "claimed_by": claims.get(item_id),
        })
        result.append(row)
    return result


__all__ = ["enrich_item_overview_rows"]
