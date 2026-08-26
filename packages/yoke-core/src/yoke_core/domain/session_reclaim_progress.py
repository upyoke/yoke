"""Episode-aware progress signals for stale-session reclaim."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from . import db_backend
from .schema_common import _get_columns as _schema_get_columns

_TURN_RUNNING = "running"

# One hook writes ``last_tool_call_at`` and the open ``session_tool_calls`` row,
# so the two stamps of a live call land within seconds of each other. Only a
# gap wider than that separates a running call from an unclosed leftover.
OPEN_TOOL_CALL_WRITE_SKEW_SECONDS = 60


def _parse_stamp(value: Optional[str]) -> Optional[datetime]:
    """Parse an ISO-8601 stamp; ``None`` when absent or unreadable."""
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


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


def open_tool_call_started_at(conn: Any, session_id: str) -> Optional[str]:
    """Start stamp of the newest unfinished ``session_tool_calls`` row.

    The stamp travels with the marker so callers can ask whether the open row
    is still credible evidence of live work. A bare "a row is open" boolean
    cannot: a harness that never writes ``completed_at`` leaves rows open
    forever, and every reader that trusted the boolean treated such a session
    as permanently busy.
    """
    try:
        columns = set(_schema_get_columns(conn, "session_tool_calls"))
    except db_backend.operational_error_types():
        return None
    if "completed_at" not in columns or "session_id" not in columns:
        return None
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    try:
        row = conn.execute(
            "SELECT MAX(started_at) AS started_at FROM session_tool_calls "
            f"WHERE session_id = {marker} AND completed_at IS NULL",
            (session_id,),
        ).fetchone()
    except db_backend.operational_error_types():
        return None
    if row is None:
        return None
    started_at = row["started_at"] if hasattr(row, "keys") else row[0]
    return str(started_at) if started_at else None


def open_tool_call_is_live(
    open_tool_call_at: Optional[str],
    activity_at: Optional[str],
) -> bool:
    """Whether an open tool-call row still evidences work in flight.

    A harness stamps ``harness_sessions.last_tool_call_at`` and inserts the
    ``session_tool_calls`` row from the same hook, so a genuinely running call
    is the session's newest recorded activity. Activity recorded well after the
    call opened proves the opposite: the session kept working and the row was
    never closed, so it is residue rather than liveness.
    """
    if open_tool_call_at is None:
        return False
    marker_at = _parse_stamp(open_tool_call_at)
    if marker_at is None:
        return False
    newest_at = _parse_stamp(activity_at)
    if newest_at is None:
        return True
    return newest_at - marker_at <= timedelta(seconds=OPEN_TOOL_CALL_WRITE_SKEW_SECONDS)


def session_turn_is_running(turn_posture: Optional[str]) -> bool:
    """True when the native turn is still in flight (thinking or a tool)."""
    return str(turn_posture or "") == _TURN_RUNNING


__all__ = [
    "OPEN_TOOL_CALL_WRITE_SKEW_SECONDS",
    "current_episode_progress_stamp",
    "live_activity_stamp",
    "newest_activity_stamp",
    "open_tool_call_is_live",
    "open_tool_call_started_at",
    "read_session_state",
    "session_turn_is_running",
]
