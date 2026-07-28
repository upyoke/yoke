"""Session-row serialization shared by claim lifecycle writers."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Dict, Optional

from . import db_backend


def lock_session_rows_for_claim_lifecycle(
    conn: Any,
    session_ids: Iterable[str],
) -> Dict[str, Optional[str]]:
    """Lock session rows before any claim-lifecycle parent or claim rows.

    Claim lifecycle writers use one global order: sorted session rows, then
    sorted parent item rows, then sorted work-claim rows. A writer that may
    create an active claim must hold the receiving session row through commit
    and re-check ``ended_at`` after acquiring this lock.

    Item-scoped cleanup that never reads or writes session state may begin at
    the item tier and use the item -> claim suffix of the same order.
    PostgreSQL supplies the production row locks. SQLite keeps stable lookup
    order while relying on database-level write serialization.
    """
    normalized = tuple(sorted({str(session_id) for session_id in session_ids}))
    if not normalized:
        return {}
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    placeholders = ", ".join(marker for _ in normalized)
    suffix = " FOR UPDATE" if db_backend.connection_is_postgres(conn) else ""
    rows = conn.execute(
        "SELECT session_id, ended_at FROM harness_sessions "
        f"WHERE session_id IN ({placeholders}) ORDER BY session_id{suffix}",
        normalized,
    ).fetchall()
    return {
        str(row["session_id"] if hasattr(row, "keys") else row[0]): (
            row["ended_at"] if hasattr(row, "keys") else row[1]
        )
        for row in rows
    }


__all__ = ["lock_session_rows_for_claim_lifecycle"]
