"""Shared reads and failure shape for Dash posture enforcement."""

from __future__ import annotations

import json
from typing import Any, Mapping, Optional

from yoke_core.domain import db_backend


def marker(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def item_row(conn: Any, item_id: int) -> dict[str, Any]:
    placeholder = marker(conn)
    cursor = conn.execute(
        "SELECT id, project_id, workflow_id, workflow_posture, "
        "COALESCE(owner, source) AS actor_id "
        f"FROM items WHERE id = {placeholder}",
        (int(item_id),),
    )
    row = cursor.fetchone()
    if row is None:
        raise LookupError(f"item {item_id} does not exist")
    columns = [str(column[0]) for column in cursor.description]
    return dict(row) if hasattr(row, "keys") else dict(zip(columns, row))


def posture(item: Mapping[str, Any]) -> dict[str, Any]:
    raw = item.get("workflow_posture") or "{}"
    if isinstance(raw, Mapping):
        return dict(raw)
    try:
        parsed = json.loads(str(raw))
    except (TypeError, ValueError):
        return {}
    return dict(parsed) if isinstance(parsed, Mapping) else {}


def failure(code: str, message: str, hint: str) -> dict[str, Any]:
    return {
        "success": False,
        "error_code": code,
        "error": message,
        "remediation_hint": hint,
    }


def dict_row(cursor: Any) -> Optional[dict[str, Any]]:
    row = cursor.fetchone()
    if row is None:
        return None
    columns = [str(column[0]) for column in cursor.description]
    return dict(row) if hasattr(row, "keys") else dict(zip(columns, row))


__all__ = ["dict_row", "failure", "item_row", "marker", "posture"]
