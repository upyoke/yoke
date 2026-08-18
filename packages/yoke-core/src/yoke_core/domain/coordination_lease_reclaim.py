"""Atomic coordination-lease cleanup for a reclaimed harness session."""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.coordination_leases import release_lease
from yoke_core.domain.schema_common import _table_exists


def release_for_reclaimed_session(
    conn: Any,
    session_id: str,
    *,
    reason: str = "stale-session-reclaimed",
) -> int:
    """Release every active lease held by ``session_id`` without committing."""
    if not _table_exists(conn, "coordination_leases"):
        return 0
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    lock = " FOR UPDATE" if db_backend.connection_is_postgres(conn) else ""
    rows = conn.execute(
        "SELECT id FROM coordination_leases "
        f"WHERE owner_kind='session' AND owner_session_id={marker} "
        f"AND released_at IS NULL ORDER BY id{lock}",
        (session_id,),
    ).fetchall()
    for row in rows:
        release_lease(conn, int(row[0]), reason, commit=False)
    return len(rows)


__all__ = ["release_for_reclaimed_session"]
