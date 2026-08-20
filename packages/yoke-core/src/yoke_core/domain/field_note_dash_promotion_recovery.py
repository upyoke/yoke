"""Recover interrupted field-note Dash promotions without duplicating items."""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import iso8601_now


# Two-arg advisory-lock classid for one in-process promotion reservation.
# Distinct from the single-bigint keys used by boot apply and universe import.
PROMOTION_RESERVATION_LOCK_CLASS = 0x464E5052  # "FNPR"


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _row_dict(cursor: Any) -> Optional[dict[str, Any]]:
    row = cursor.fetchone()
    if row is None:
        return None
    columns = [str(column[0]) for column in cursor.description]
    return dict(row) if hasattr(row, "keys") else dict(zip(columns, row))


def _lock_flag(row: Any) -> bool:
    if row is None:
        return False
    if hasattr(row, "keys"):
        return bool(next(iter(row.values())))
    return bool(row[0])


def try_hold_promotion_reservation(conn: Any, entry_id: int) -> bool:
    """Hold the in-process reservation lock, or return False when another
    connection already holds it.

    Postgres session advisory locks drop when the connection dies, so a crash
    is immediately distinguishable from a live concurrent promote. SQLite
    callers have no advisory locks and therefore always proceed.
    """
    if not db_backend.connection_is_postgres(conn):
        return True
    return _lock_flag(conn.execute(
        "SELECT pg_try_advisory_lock(%s, %s)",
        (PROMOTION_RESERVATION_LOCK_CLASS, int(entry_id)),
    ).fetchone())


def release_promotion_reservation(conn: Any, entry_id: int) -> None:
    """Release this connection's reservation lock if held."""
    if not db_backend.connection_is_postgres(conn):
        return
    conn.execute(
        "SELECT pg_advisory_unlock(%s, %s)",
        (PROMOTION_RESERVATION_LOCK_CLASS, int(entry_id)),
    )


def find_unlinked_promoted_dash(
    conn: Any,
    *,
    title: str,
    created_at: str,
) -> Optional[int]:
    """Return the earliest unlinked Dash matching this reservation."""
    marker = _p(conn)
    row = _row_dict(conn.execute(
        "SELECT i.id FROM items i "
        f"WHERE i.workflow_id = {marker} AND i.title = {marker} "
        f"AND i.created_at >= {marker} AND NOT EXISTS ("
        "SELECT 1 FROM ouroboros_entry_dispositions d "
        f"WHERE d.item_id = i.id) "
        "ORDER BY i.id ASC LIMIT 1",
        ("dash", title, created_at),
    ))
    if row is None:
        return None
    return int(row["id"])


def persist_completed_promotion(
    conn: Any,
    *,
    entry_id: int,
    item_id: int,
) -> None:
    """Link the Dash onto its field note and mark the disposition completed."""
    marker = _p(conn)
    now = iso8601_now()
    conn.execute(
        "UPDATE ouroboros_entry_dispositions "
        f"SET state = 'completed', item_id = {marker}, "
        f"failure_reason = NULL, updated_at = {marker} "
        f"WHERE entry_id = {marker}",
        (int(item_id), now, int(entry_id)),
    )
    conn.execute(
        "UPDATE ouroboros_entries "
        f"SET reviewed_at = COALESCE(reviewed_at, {marker}) "
        f"WHERE id = {marker}",
        (now, int(entry_id)),
    )
    conn.commit()


__all__ = [
    "PROMOTION_RESERVATION_LOCK_CLASS",
    "find_unlinked_promoted_dash",
    "persist_completed_promotion",
    "release_promotion_reservation",
    "try_hold_promotion_reservation",
]
