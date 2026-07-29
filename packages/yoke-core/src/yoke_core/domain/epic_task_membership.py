"""Durable generated-task membership finalization."""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _column_exists, _table_exists


MEMBERSHIP_FINALIZED_COLUMN = "generated_task_membership_finalized_at"


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def snapshot_available(conn: Any) -> bool:
    """Return whether item-level membership snapshots can be persisted."""
    return _table_exists(conn, "items") and _column_exists(
        conn,
        "items",
        MEMBERSHIP_FINALIZED_COLUMN,
    )


def membership_is_finalized(conn: Any, item_id: int) -> bool:
    """Read the item snapshot with per-task markers as rolling fallback."""
    marker = _p(conn)
    if snapshot_available(conn):
        row = conn.execute(
            f"SELECT {MEMBERSHIP_FINALIZED_COLUMN} FROM items WHERE id={marker}",
            (int(item_id),),
        ).fetchone()
        if row is not None:
            value = row[MEMBERSHIP_FINALIZED_COLUMN] if hasattr(row, "keys") else row[0]
            if value is not None:
                return True
    if not _table_exists(conn, "epic_tasks") or not _column_exists(
        conn,
        "epic_tasks",
        "scope_finalized_at",
    ):
        return False
    return (
        conn.execute(
            "SELECT 1 FROM epic_tasks "
            f"WHERE epic_id={marker} AND scope_finalized_at IS NOT NULL "
            "LIMIT 1",
            (int(item_id),),
        ).fetchone()
        is not None
    )


def stamp_membership_finalized(conn: Any, item_id: int) -> bool:
    """Persist the current task membership, including an empty set."""
    if not snapshot_available(conn):
        return False
    marker = _p(conn)
    cursor = conn.execute(
        f"UPDATE items SET {MEMBERSHIP_FINALIZED_COLUMN}=CURRENT_TIMESTAMP "
        f"WHERE id={marker}",
        (int(item_id),),
    )
    return cursor.rowcount > 0


def clear_membership_finalized(conn: Any, item_id: int) -> int:
    """Clear one durable item-level membership snapshot."""
    if not snapshot_available(conn):
        return 0
    marker = _p(conn)
    cursor = conn.execute(
        f"UPDATE items SET {MEMBERSHIP_FINALIZED_COLUMN}=NULL "
        f"WHERE id={marker} AND {MEMBERSHIP_FINALIZED_COLUMN} IS NOT NULL",
        (int(item_id),),
    )
    return max(int(cursor.rowcount or 0), 0)


def backfill_membership_finalized(conn: Any) -> None:
    """Project legacy per-task finalization into item-level snapshots."""
    if not snapshot_available(conn):
        return
    conn.execute(
        f"UPDATE items SET {MEMBERSHIP_FINALIZED_COLUMN}=CURRENT_TIMESTAMP "
        f"WHERE {MEMBERSHIP_FINALIZED_COLUMN} IS NULL "
        "AND EXISTS (SELECT 1 FROM epic_tasks "
        "WHERE epic_tasks.epic_id=items.id "
        "AND epic_tasks.scope_finalized_at IS NOT NULL)"
    )


__all__ = [
    "MEMBERSHIP_FINALIZED_COLUMN",
    "backfill_membership_finalized",
    "clear_membership_finalized",
    "membership_is_finalized",
    "snapshot_available",
    "stamp_membership_finalized",
]
