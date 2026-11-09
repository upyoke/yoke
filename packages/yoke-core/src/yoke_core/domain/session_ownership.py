"""Actor ownership policy for stamped session identities."""

from __future__ import annotations

from typing import Any


def session_ownership_refusal(
    conn: Any,
    session_id: str,
    actor_id: int | None,
) -> str | None:
    """Refuse a stamped id whose existing session belongs to another actor.

    An id with no session row yet is accepted: the observation itself is
    what registers a session that a hook has only just started stamping.
    """
    if actor_id is None or not session_id:
        return None
    from yoke_core.domain import db_backend

    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        f"SELECT actor_id FROM harness_sessions WHERE session_id = {marker}",
        (session_id,),
    ).fetchone()
    if row is None:
        return None
    stored = row.get("actor_id") if isinstance(row, dict) else row[0]
    if stored is None or int(stored) == int(actor_id):
        return None
    return (
        "stamped session id belongs to a different actor; relay through the "
        "connection whose actor owns the session"
    )
