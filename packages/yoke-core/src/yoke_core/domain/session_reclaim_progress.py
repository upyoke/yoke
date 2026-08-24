"""Episode-aware progress signals for stale-session reclaim."""

from __future__ import annotations

from typing import Any, Optional

from . import db_backend
from .schema_common import _get_columns as _schema_get_columns


def newest_activity_stamp(*values: Optional[str]) -> Optional[str]:
    """Return the newest present ISO-8601 stamp."""
    present = [value for value in values if value]
    return max(present) if present else None


def current_episode_progress_stamp(
    last_tool_call_at: Optional[str],
    episode_started_at: Optional[str],
) -> Optional[str]:
    """Anchor existing tool progress to the current episode boundary."""
    if last_tool_call_at is None:
        return None
    return newest_activity_stamp(last_tool_call_at, episode_started_at)


def read_session_state(
    conn: Any,
    session_id: str,
) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str], Optional[str]]:
    """Return executor, heartbeat, end, tool-call, and episode stamps."""
    try:
        columns = set(_schema_get_columns(conn, "harness_sessions"))
    except db_backend.operational_error_types():
        return (None, None, None, None, None)
    if not columns:
        return (None, None, None, None, None)
    selected = ["last_heartbeat", "ended_at"]
    for optional in ("executor", "last_tool_call_at", "episode_started_at"):
        if optional in columns:
            selected.append(optional)
    try:
        marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
        row = conn.execute(
            f"SELECT {', '.join(selected)} FROM harness_sessions "
            f"WHERE session_id = {marker}",
            (session_id,),
        ).fetchone()
    except db_backend.operational_error_types():
        return (None, None, None, None, None)
    if row is None:
        return (None, None, None, None, None)
    values = (
        {name: row[name] for name in selected}
        if hasattr(row, "keys")
        else dict(zip(selected, row))
    )
    return (
        values.get("executor"),
        values.get("last_heartbeat"),
        values.get("ended_at"),
        values.get("last_tool_call_at"),
        values.get("episode_started_at"),
    )


__all__ = [
    "current_episode_progress_stamp",
    "newest_activity_stamp",
    "read_session_state",
]
