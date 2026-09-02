"""Durable relay-launch context for registered harness sessions."""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend


def session_was_relay_launched(conn: Any, session_id: str) -> bool:
    """Return whether a session was correlated to a Yoke relay launch.

    Unknown launch context is treated as relay-managed so a schema or read
    failure cannot enable an unenforceable Stop denial on a headless worker.
    """
    if not session_id:
        return False
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    try:
        row = conn.execute(
            "SELECT 1 FROM session_launches "
            f"WHERE registered_session_id={marker} LIMIT 1",
            (session_id,),
        ).fetchone()
    except Exception:  # noqa: BLE001 - fail safe against an unenforceable denial
        return True
    return row is not None


__all__ = ["session_was_relay_launched"]
