"""Allowlisted Items ordering and sort-bound, verbatim keyset cursors."""

from __future__ import annotations

import json
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.work_claim_targets import scope_int_sql

SORT_COLUMNS = (
    "id",
    "project",
    "title",
    "workflow",
    "status",
    "owner",
    "claimed_by",
    "updated_at",
)
SORT_DIRECTIONS = ("asc", "desc")
ROSTER_SORT_EXPRESSION = "COALESCE(NULLIF(i.updated_at, ''), i.created_at)"


class RosterCursorError(ValueError):
    """An invalid sort or cursor, with an actionable recovery."""


def sort_expression(conn: Any, column: str, direction: str) -> str:
    if column not in SORT_COLUMNS or direction not in SORT_DIRECTIONS:
        raise RosterCursorError(
            "Unknown Items sort column or direction. Choose a column header and retry."
        )
    if column == "updated_at":
        return ROSTER_SORT_EXPRESSION
    if column == "id":
        width = 20
        sequence = (
            f"LPAD(CAST(i.project_sequence AS TEXT), {width}, '0')"
            if db_backend.connection_is_postgres(conn)
            else f"printf('%0{width}d', i.project_sequence)"
        )
        return f"LOWER(p.public_item_prefix) || '-' || {sequence}"
    if column == "project":
        return "LOWER(p.slug)"
    if column in ("title", "workflow", "status"):
        field = "workflow_id" if column == "workflow" else column
        return f"LOWER(i.{field})"
    if column == "owner":
        return (
            "LOWER(COALESCE((SELECT a.name FROM actors a "
            "WHERE CAST(a.id AS TEXT) = i.owner), "
            "NULLIF(NULLIF(i.owner, 'none'), 'null'), ''))"
        )
    if not _table_exists(conn, "work_claims"):
        return "''"
    item_id = scope_int_sql(conn, "wc.scope", "item_id")
    return (
        "LOWER(COALESCE((SELECT COALESCE(a.name, hs.executor, wc.session_id) "
        "FROM work_claims wc LEFT JOIN harness_sessions hs ON hs.session_id = wc.session_id "
        "LEFT JOIN actors a ON a.id = hs.actor_id "
        f"WHERE wc.target_kind = 'item' AND wc.released_at IS NULL AND {item_id} = i.id "
        "ORDER BY wc.id DESC LIMIT 1), ''))"
    )


def encode_cursor(
    sort_value: str, item_id: int, column: str = "updated_at", direction: str = "desc"
) -> str:
    return json.dumps(
        [column, direction, sort_value, int(item_id)], separators=(",", ":")
    )


def decode_cursor(
    cursor: str, column: str = "updated_at", direction: str = "desc"
) -> tuple[str, int]:
    try:
        stored_column, stored_direction, value, item_id = json.loads(cursor)
        if stored_column != column or stored_direction != direction:
            raise ValueError("sort changed")
        if not isinstance(value, str) or type(item_id) is not int:
            raise ValueError("invalid key")
        return value, item_id
    except (ValueError, TypeError) as exc:
        raise RosterCursorError(
            "Invalid or mismatched sort cursor. Reload the Items page to restart paging."
        ) from exc
