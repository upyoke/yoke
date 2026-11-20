"""Episode-aware progress signals for stale-session reclaim."""

from __future__ import annotations

from datetime import datetime, timedelta
from yoke_contracts.timestamps import parse_instant, utc_now
from typing import Any, Mapping, Optional

from . import db_backend
from .schema_common import _get_columns as _schema_get_columns

# Tolerate nearby completions (for example, a nested call). A completion well
# after a still-open row is evidence that the row was left behind.
OPEN_TOOL_CALL_WRITE_SKEW_SECONDS = 60


def parse_stamp(value: datetime | str | None) -> datetime | None:
    """Read an aware instant, preserving absence and refusing invalid values."""
    return None if value is None else parse_instant(value)


def newest_activity_stamp(*values: datetime | str | None) -> datetime | None:
    """Return the newest present instant without comparing encodings."""
    present = [parse_instant(value) for value in values if value is not None]
    return max(present) if present else None


def current_episode_progress_stamp(
    last_tool_call_at: datetime | str | None,
    episode_started_at: datetime | str | None,
) -> datetime | None:
    """Anchor existing tool progress to the current episode boundary."""
    if last_tool_call_at is None:
        return None
    return newest_activity_stamp(last_tool_call_at, episode_started_at)


def live_activity_stamp() -> datetime:
    """Present-moment instant so in-flight work is not classified stale."""
    return utc_now()


def open_tool_call_started_at(conn: Any, session_id: str) -> datetime | None:
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
    return parse_stamp(started_at)


def open_tool_call_is_live(
    open_tool_call_at: datetime | str | None,
    activity_at: datetime | str | None,
) -> bool:
    """Whether an open tool-call row still evidences work in flight.

    The start hook opens the ``session_tool_calls`` row and stamps the session's
    running turn posture. The completion hook stamps ``last_tool_call_at``.
    A completion well after the call opened indicates that the open row was
    left behind while the session kept working.
    """
    if open_tool_call_at is None:
        return False
    marker_at = parse_stamp(open_tool_call_at)
    if marker_at is None:
        return False
    newest_at = parse_stamp(activity_at)
    if newest_at is None:
        return True
    return newest_at - marker_at <= timedelta(seconds=OPEN_TOOL_CALL_WRITE_SKEW_SECONDS)



def tool_activity_stamp(row: Mapping[str, Any]) -> datetime | None:
    """The newest tool call by the session or any subagent it runs.

    ``last_tool_call_at`` moves only on the parent's own calls, because
    delivery asks when the parent last ran a hook. Liveness and reclaim ask
    whether the session is doing work, and a parent waiting on a working
    subagent is: its child calls stamp ``last_child_tool_call_at``.
    """
    return newest_activity_stamp(
        row.get("last_tool_call_at"), row.get("last_child_tool_call_at")
    )


def session_turn_is_running(turn_posture: Optional[str]) -> bool:
    """Read native turn phase without making a liveness decision."""
    return turn_posture == "running"


__all__ = [
    "OPEN_TOOL_CALL_WRITE_SKEW_SECONDS",
    "current_episode_progress_stamp",
    "live_activity_stamp",
    "newest_activity_stamp",
    "open_tool_call_is_live",
    "open_tool_call_started_at",
    "parse_stamp",
    "session_turn_is_running",
    "tool_activity_stamp",
]
