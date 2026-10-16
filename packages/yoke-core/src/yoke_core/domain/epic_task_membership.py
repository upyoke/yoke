"""Durable generated-task membership finalization."""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend


MEMBERSHIP_FINALIZED_COLUMN = "generated_task_membership_finalized_at"


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def membership_is_finalized(conn: Any, item_id: int) -> bool:
    """Read the durable item-level task membership snapshot."""
    marker = _p(conn)
    row = conn.execute(
        f"SELECT {MEMBERSHIP_FINALIZED_COLUMN} FROM items WHERE id={marker}",
        (int(item_id),),
    ).fetchone()
    if row is None:
        return False
    value = row[MEMBERSHIP_FINALIZED_COLUMN] if hasattr(row, "keys") else row[0]
    return value is not None


def stamp_membership_finalized(conn: Any, item_id: int) -> bool:
    """Persist the current task membership, including an empty set."""
    marker = _p(conn)
    cursor = conn.execute(
        f"UPDATE items SET {MEMBERSHIP_FINALIZED_COLUMN}=CURRENT_TIMESTAMP "
        f"WHERE id={marker}",
        (int(item_id),),
    )
    return cursor.rowcount > 0


def clear_membership_finalized(conn: Any, item_id: int) -> int:
    """Clear one durable item-level membership snapshot."""
    marker = _p(conn)
    cursor = conn.execute(
        f"UPDATE items SET {MEMBERSHIP_FINALIZED_COLUMN}=NULL "
        f"WHERE id={marker} AND {MEMBERSHIP_FINALIZED_COLUMN} IS NOT NULL",
        (int(item_id),),
    )
    return max(int(cursor.rowcount or 0), 0)


__all__ = [
    "MEMBERSHIP_FINALIZED_COLUMN",
    "clear_membership_finalized",
    "membership_is_finalized",
    "stamp_membership_finalized",
]
