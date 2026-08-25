"""Episode-aware progress signals for stale-session reclaim."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from . import db_backend
from .schema_common import _get_columns as _schema_get_columns

_TURN_RUNNING = "running"


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


def live_activity_stamp() -> str:
    """Present-moment stamp so in-flight work is not classified stale."""
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def read_session_state(
    conn: Any,
    session_id: str,
) -> tuple[
    Optional[str],
    Optional[str],
    Optional[str],
    Optional[str],
    Optional[str],
    Optional[str],
]:
    """Return executor, heartbeat, end, tool-call, episode, and turn posture."""
    empty = (None, None, None, None, None, None)
    try:
        columns = set(_schema_get_columns(conn, "harness_sessions"))
    except db_backend.operational_error_types():
        return empty
    if not columns:
        return empty
    selected = ["last_heartbeat", "ended_at"]
    for optional in (
        "executor",
        "last_tool_call_at",
        "episode_started_at",
        "turn_posture",
    ):
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
        return empty
    if row is None:
        return empty
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
        values.get("turn_posture"),
    )


def session_has_open_tool_call(conn: Any, session_id: str) -> bool:
    """True when a ``session_tool_calls`` row is still unfinished."""
    try:
        columns = set(_schema_get_columns(conn, "session_tool_calls"))
    except db_backend.operational_error_types():
        return False
    if "completed_at" not in columns or "session_id" not in columns:
        return False
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    try:
        row = conn.execute(
            "SELECT 1 FROM session_tool_calls "
            f"WHERE session_id = {marker} AND completed_at IS NULL LIMIT 1",
            (session_id,),
        ).fetchone()
    except db_backend.operational_error_types():
        return False
    return row is not None


def session_turn_is_running(turn_posture: Optional[str]) -> bool:
    """True when the native turn is still in flight (thinking or a tool)."""
    return str(turn_posture or "") == _TURN_RUNNING


__all__ = [
    "current_episode_progress_stamp",
    "live_activity_stamp",
    "newest_activity_stamp",
    "read_session_state",
    "session_has_open_tool_call",
    "session_turn_is_running",
]
