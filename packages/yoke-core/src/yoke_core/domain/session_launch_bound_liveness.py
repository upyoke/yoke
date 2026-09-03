"""Decide whether a launch's bound session is a live, working session.

A launch can reach its deadline still marked ``awaiting_registration`` even
though its bound session came up, took the item's work claim, and is running.
Closing that launch ``failed`` and cancelling its instruction is bookkeeping
that contradicts reality: the session card then reads ``Latest: expired`` for a
session that is actively holding the item. This module reads the session's own
row and its claims to decide whether a bound launch has in fact reached a live,
working session, so the deadline sweep can close it delivered instead.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.schema_common import _column_exists, _table_exists
from yoke_core.domain.session_launch_store import marker, parse_time, value
from yoke_core.domain.session_launch_types import LaunchRecord


# A bound session with a tool call this recent is treated as actively working
# even without a held claim. Wide enough to cover a session mid-turn, far short
# of the stale-session window that would reclaim it.
BOUND_ACTIVE_TOOL_CALL_SECONDS = 600


def _holds_active_claim(conn: Any, session_id: str) -> bool:
    if not _table_exists(conn, "work_claims"):
        return False
    p = marker(conn)
    row = conn.execute(
        f"SELECT 1 FROM work_claims WHERE session_id={p} AND released_at IS NULL LIMIT 1",
        (session_id,),
    ).fetchone()
    return row is not None


def bound_session_delivered(conn: Any, launch: LaunchRecord, *, now: str) -> bool:
    """Return whether this launch's registered session is live and working.

    True when the bound session is neither ended nor terminated and either
    holds an active work claim — unambiguously working on its mandate — or made
    a tool call recently enough to prove it is mid-turn even before it has
    taken a claim.
    """
    session_id = str(launch.registered_session_id or "").strip()
    if not session_id or not _table_exists(conn, "harness_sessions"):
        return False
    p = marker(conn)
    has_last_tool = _column_exists(conn, "harness_sessions", "last_tool_call_at")
    has_terminated = _column_exists(conn, "harness_sessions", "terminated_at")
    tool_column = "last_tool_call_at" if has_last_tool else "NULL"
    terminated_column = "terminated_at" if has_terminated else "NULL"
    row = conn.execute(
        f"SELECT ended_at, {terminated_column} AS terminated, "
        f"{tool_column} AS last_tool "
        f"FROM harness_sessions WHERE session_id={p}",
        (session_id,),
    ).fetchone()
    if row is None:
        return False
    if value(row, "ended_at", 0) or value(row, "terminated", 1):
        return False
    if _holds_active_claim(conn, session_id):
        return True
    last_tool = str(value(row, "last_tool", 2) or "").strip()
    if not last_tool:
        return False
    try:
        elapsed = (parse_time(now) - parse_time(last_tool)).total_seconds()
    except (TypeError, ValueError):
        return False
    return elapsed <= BOUND_ACTIVE_TOOL_CALL_SECONDS


__all__ = ["BOUND_ACTIVE_TOOL_CALL_SECONDS", "bound_session_delivered"]
