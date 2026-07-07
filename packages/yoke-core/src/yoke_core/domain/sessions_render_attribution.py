"""Session current-item attribution helpers."""

from __future__ import annotations

from typing import Any, Dict, Optional

from .sessions_analytics import SessionError
from .sessions_queries import _now_iso, normalize_session_item_id

def set_current_item(
    conn: Any,
    session_id: str,
    item_id: str,
    item_status: Optional[str] = None,
) -> None:
    """Set the current item focus for a session.

    Before setting the new item, copies current values to recent_item_*
    fields if ``current_item_id`` was non-NULL.  Silently no-ops if the
    session is ended.

    Args:
        conn: DB connection.
        session_id: Session to update.
        item_id: Item identifier (stored bare numeric when possible).
        item_status: Optional status to record in ``recent_item_status``
            when the current item becomes the recent item.
    """
    now = _now_iso()
    item_id = normalize_session_item_id(item_id)
    row = conn.execute(
        "SELECT ended_at, current_item_id, current_item_set_at "
        "FROM harness_sessions WHERE session_id = %s",
        (session_id,),
    ).fetchone()
    if row is None:
        raise SessionError("NOT_FOUND", f"Session '{session_id}' not found.")
    if row[0] is not None:
        # Session ended — silently no-op
        return

    # Move current to recent if non-NULL
    if row[1] is not None:
        conn.execute(
            "UPDATE harness_sessions SET "
            "recent_item_id = %s, recent_item_status = %s, recent_item_recorded_at = %s "
            "WHERE session_id = %s",
            (row[1], item_status, row[2], session_id),
        )

    conn.execute(
        "UPDATE harness_sessions SET "
        "current_item_id = %s, current_item_set_at = %s "
        "WHERE session_id = %s",
        (item_id, now, session_id),
    )
    conn.commit()


def get_session_attribution(
    conn: Any,
    session_id: str,
) -> Dict[str, Any]:
    """Return attribution fields for a session as a dict.

    Returns an empty dict if the session is not found.
    """
    row = conn.execute(
        "SELECT current_item_id, current_item_set_at, "
        "recent_item_id, recent_item_status, recent_item_recorded_at "
        "FROM harness_sessions WHERE session_id = %s",
        (session_id,),
    ).fetchone()
    if row is None:
        return {}
    return {
        "current_item_id": row[0],
        "current_item_set_at": row[1],
        "recent_item_id": row[2],
        "recent_item_status": row[3],
        "recent_item_recorded_at": row[4],
    }


def clear_current_item(
    conn: Any,
    session_id: str,
) -> None:
    """Clear the current item focus, moving current to recent first.

    Args:
        conn: DB connection.
        session_id: Session to update.
    """
    row = conn.execute(
        "SELECT current_item_id, current_item_set_at "
        "FROM harness_sessions WHERE session_id = %s",
        (session_id,),
    ).fetchone()
    if row is None:
        raise SessionError("NOT_FOUND", f"Session '{session_id}' not found.")

    # Move current to recent if non-NULL
    if row[0] is not None:
        conn.execute(
            "UPDATE harness_sessions SET "
            "recent_item_id = %s, recent_item_recorded_at = %s "
            "WHERE session_id = %s",
            (row[0], row[1], session_id),
        )

    conn.execute(
        "UPDATE harness_sessions SET "
        "current_item_id = NULL, current_item_set_at = NULL "
        "WHERE session_id = %s",
        (session_id,),
    )
    conn.commit()
