"""Foreign-key-safe session identity for session-control requests."""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend


def registered_request_session_id(
    conn: Any,
    session_id: str | None,
) -> str | None:
    """Return the caller session only when it names a registered harness row."""
    candidate = str(session_id or "").strip()
    if not candidate:
        return None
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        f"SELECT 1 FROM harness_sessions WHERE session_id = {marker}",
        (candidate,),
    ).fetchone()
    return candidate if row is not None else None


__all__ = ["registered_request_session_id"]
