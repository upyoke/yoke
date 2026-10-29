"""Seed a stored session mode the way an older build may have left it."""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend


def seed_session_mode(conn: Any, session_id: str, mode: str, row: dict) -> dict:
    """Write ``mode`` directly, bypassing the wait-or-parked write check."""
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    conn.execute(
        f"UPDATE harness_sessions SET mode={marker} WHERE session_id={marker}",
        (mode, session_id),
    )
    conn.commit()
    return {**row, "mode": mode}
