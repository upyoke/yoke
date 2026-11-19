"""Record a subagent's tool calls without letting them speak for the parent.

A subagent shares its parent's session id, so before this module every child
call stamped the parent's ``last_tool_call_at`` and turn posture. A parent
that started a background agent and ended its turn then read as a turn in
flight for as long as the child worked, while every hook in that window was
the child's and declined to read the parent's inbox. Delivery waited on a
hook the parent was not going to run and the starvation clock never started.

Child calls are still activity, so they still land in ``session_tool_calls``
— marked with ``agent_type`` — and stamp ``last_child_tool_call_at`` and the
call count, which keep liveness and reclaim seeing a working session. They
never move ``last_tool_call_at``, ``turn_posture`` or the parent's open-call
projection: those answer "when did the parent's own hook last run", the
question delivery asks.

A database that has not converged the ``agent_type`` column records no child
row at all, because an unmarked row would read as the parent's open call.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import instant_parameter
from yoke_core.domain.schema_common import _get_columns
from yoke_core.domain.session_tool_call_start_reconcile import adopt_earlier_start

#: The envelope key the observe pipeline sets for a subagent's call (Claude
#: ``agent_type``, Codex ``agent:`` dispatch, ``YOKE_HOOK_AGENT_TYPE``).
CHILD_AGENT_ENVELOPE_KEY = "agent"


def child_agent_type(envelope: Dict[str, Any]) -> str:
    """The subagent that made this call, or ``""`` for the parent's own."""
    value = envelope.get(CHILD_AGENT_ENVELOPE_KEY)
    return value.strip() if isinstance(value, str) else ""


def _columns(conn: Any, table: str) -> set:
    try:
        return set(_get_columns(conn, table))
    except db_backend.operational_error_types():
        return set()


def _bump_child_activity(conn: Any, p: str, session_id: str, at: Any) -> None:
    if "last_child_tool_call_at" not in _columns(conn, "harness_sessions"):
        return
    conn.execute(
        "UPDATE harness_sessions SET last_child_tool_call_at = CASE "
        f"WHEN last_child_tool_call_at IS NULL OR last_child_tool_call_at < {p} "
        f"THEN {p} ELSE last_child_tool_call_at END, "
        "tool_call_count = COALESCE(tool_call_count, 0) + 1 "
        f"WHERE session_id = {p}",
        (at, at, session_id),
    )


def apply_child_envelope_state(
    conn: Any,
    envelope: Dict[str, Any],
    *,
    agent_type: str,
    observed_at: datetime,
    started: bool,
    counts_as_activity: bool,
) -> None:
    """Open or close one child call row, and stamp child activity on close."""
    session_id = envelope["session_id"]
    tool_use_id = envelope.get("tool_use_id")
    if not isinstance(tool_use_id, str) or not tool_use_id:
        return
    if "agent_type" not in _columns(conn, "session_tool_calls"):
        return
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    stamp = instant_parameter(conn, observed_at)
    tool_name = envelope.get("tool_name")
    if started:
        cursor = conn.execute(
            "INSERT INTO session_tool_calls "
            "(session_id, tool_use_id, tool_name, started_at, agent_type) "
            f"VALUES ({p}, {p}, {p}, {p}, {p}) "
            "ON CONFLICT(session_id, tool_use_id) DO NOTHING",
            (session_id, tool_use_id, tool_name, stamp, agent_type),
        )
        if getattr(cursor, "rowcount", 0) <= 0:
            adopt_earlier_start(
                conn,
                placeholder=p,
                session_id=session_id,
                tool_use_id=tool_use_id,
                started_at=observed_at,
            )
        return
    outcome = envelope.get("event_outcome")
    cursor = conn.execute(
        f"UPDATE session_tool_calls SET completed_at = {p}, outcome = {p} "
        f"WHERE session_id = {p} AND tool_use_id = {p} AND completed_at IS NULL",
        (stamp, outcome, session_id, tool_use_id),
    )
    closed = getattr(cursor, "rowcount", 0) > 0
    if not closed:
        cursor = conn.execute(
            "INSERT INTO session_tool_calls "
            "(session_id, tool_use_id, tool_name, started_at, completed_at, "
            " outcome, agent_type) "
            f"VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}) "
            "ON CONFLICT(session_id, tool_use_id) DO NOTHING",
            (session_id, tool_use_id, tool_name, stamp, stamp, outcome, agent_type),
        )
        closed = getattr(cursor, "rowcount", 0) > 0
    if closed and counts_as_activity:
        _bump_child_activity(conn, p, session_id, stamp)


__all__ = [
    "CHILD_AGENT_ENVELOPE_KEY",
    "apply_child_envelope_state",
    "child_agent_type",
]
