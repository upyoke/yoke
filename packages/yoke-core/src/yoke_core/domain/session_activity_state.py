"""Session & tool-call activity state — the post telemetry-only-events app-state owner.

The telemetry-only events cutover makes the ``events`` table telemetry-only: session liveness, tool-call
counts, and the open-tool-call ledger move to first-class state —
``harness_sessions.last_tool_call_at`` / ``tool_call_count`` and the
rolling ``session_tool_calls`` table. The observe pipeline
(:func:`yoke_core.domain.observe_event_emission.insert_event`) calls
:func:`apply_envelope_state` in the same transaction as each telemetry
insert; readers (``session_reclaim_activity``, ``sessions_cleanup``,
claim-acquire freshness, the orphan sweep, and the PreToolUse lint
guardrails) consume only this state, never the events ledger.

Schema-tolerance contract: many test fixtures build minimal
``harness_sessions`` / no ``session_tool_calls`` shapes. Every writer here
introspects via ``information_schema`` (the codebase's established
minimal-fixture pattern) and silently skips what the schema cannot hold —
mirroring how ``insert_event`` no-ops without an ``events`` table.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _get_columns as _schema_get_columns

# Bounded command text retained for the PreToolUse lint guardrails (R4).
# Partially duplicates telemetry's envelope tool_input on purpose: the
# lints must keep their signal after the events ledger becomes
# telemetry-only.
COMMAND_SUMMARY_MAX_CHARS = 500

# Event names that bump ``last_tool_call_at`` / ``tool_call_count``.
# Exactly the pair the pre telemetry-only-events activity readers scanned for — denied calls
# already map to HarnessToolCallFailed at envelope-build time, while
# StructuredExit / LifecycleMutationDetected never counted as activity.
ACTIVITY_EVENT_NAMES: Tuple[str, ...] = (
    "HarnessToolCallCompleted",
    "HarnessToolCallFailed",
)

# Event names that close an open ``session_tool_calls`` row. Mirrors the
# orphan sweep's historical completion-match set: any of these sharing
# (session_id, tool_use_id) with a Started row means the call finished.
COMPLETION_EVENT_NAMES: Tuple[str, ...] = (
    "HarnessToolCallCompleted",
    "HarnessToolCallFailed",
    "HarnessToolCallStructuredExit",
    "HarnessLifecycleMutationDetected",
    "HarnessToolCallDenied",
)

_STARTED_EVENT_NAME = "HarnessToolCallStarted"


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _columns(conn: Any, table: str) -> set:
    try:
        return set(_schema_get_columns(conn, table))
    except db_backend.operational_error_types():
        return set()


def has_session_tool_calls_table(conn: Any) -> bool:
    return bool(_columns(conn, "session_tool_calls"))


def session_activity_columns_present(conn: Any) -> bool:
    return "last_tool_call_at" in _columns(conn, "harness_sessions")


def episode_column_present(conn: Any) -> bool:
    return "episode_started_at" in _columns(conn, "harness_sessions")


def truncate_command_summary(command: Optional[str]) -> Optional[str]:
    if not command:
        return None
    return str(command)[:COMMAND_SUMMARY_MAX_CHARS]


def _envelope_command_summary(envelope: Dict[str, Any]) -> Optional[str]:
    context = envelope.get("context")
    if not isinstance(context, dict):
        return None
    detail = context.get("detail")
    if not isinstance(detail, dict):
        return None
    tool_input = detail.get("tool_input")
    if isinstance(tool_input, str) and tool_input:
        return truncate_command_summary(tool_input)
    return None


def record_tool_call_started(
    conn: Any,
    *,
    session_id: str,
    tool_use_id: str,
    tool_name: Optional[str],
    started_at: str,
    command_summary: Optional[str] = None,
) -> bool:
    """Open a ``session_tool_calls`` row. Duplicate Started rows no-op."""
    if not session_id or not tool_use_id:
        return False
    if not has_session_tool_calls_table(conn):
        return False
    p = _p(conn)
    cursor = conn.execute(
        "INSERT INTO session_tool_calls "
        "(session_id, tool_use_id, tool_name, started_at, command_summary) "
        f"VALUES ({p}, {p}, {p}, {p}, {p}) "
        "ON CONFLICT(session_id, tool_use_id) DO NOTHING",
        (
            session_id,
            tool_use_id,
            tool_name,
            started_at,
            truncate_command_summary(command_summary),
        ),
    )
    return getattr(cursor, "rowcount", 0) > 0


def record_tool_call_finished(
    conn: Any,
    *,
    session_id: str,
    tool_use_id: Optional[str],
    tool_name: Optional[str],
    event_name: str,
    outcome: Optional[str],
    completed_at: str,
    command_summary: Optional[str] = None,
    bump_activity: bool = True,
) -> None:
    """Close the open row and bump the session activity columns.

    A completion without a prior Started row (the pre-hook dropped the
    payload, or the call predates the table) inserts a closed row so the
    lint guardrails and counts stay coherent. ``bump_activity`` bumps
    ``last_tool_call_at`` / ``tool_call_count`` only for
    :data:`ACTIVITY_EVENT_NAMES` — the orphan sweep's synthesized
    interrupted completions pass ``bump_activity=False`` because the
    session is ending and sweep time is not agent activity.
    """
    if not session_id:
        return
    p = _p(conn)
    if tool_use_id and has_session_tool_calls_table(conn):
        summary = truncate_command_summary(command_summary)
        cursor = conn.execute(
            "UPDATE session_tool_calls "
            f"SET completed_at = {p}, outcome = {p}, "
            f"    command_summary = COALESCE(command_summary, {p}) "
            f"WHERE session_id = {p} AND tool_use_id = {p} "
            "  AND completed_at IS NULL",
            (completed_at, outcome, summary, session_id, tool_use_id),
        )
        if getattr(cursor, "rowcount", 0) == 0:
            conn.execute(
                "INSERT INTO session_tool_calls "
                "(session_id, tool_use_id, tool_name, started_at, "
                " completed_at, outcome, command_summary) "
                f"VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}) "
                "ON CONFLICT(session_id, tool_use_id) DO NOTHING",
                (
                    session_id, tool_use_id, tool_name, completed_at,
                    completed_at, outcome, summary,
                ),
            )
    if bump_activity and event_name in ACTIVITY_EVENT_NAMES:
        bump_session_tool_activity(
            conn, session_id=session_id, at=completed_at,
        )


def bump_session_tool_activity(
    conn: Any, *, session_id: str, at: str
) -> None:
    """Stamp ``last_tool_call_at`` and increment ``tool_call_count``."""
    if not session_activity_columns_present(conn):
        return
    p = _p(conn)
    conn.execute(
        "UPDATE harness_sessions "
        f"SET last_tool_call_at = {p}, "
        "    tool_call_count = COALESCE(tool_call_count, 0) + 1 "
        f"WHERE session_id = {p}",
        (at, session_id),
    )


def apply_envelope_state(conn: Any, envelope: Dict[str, Any]) -> None:
    """Project one observe-pipeline envelope onto the activity state.

    Called by ``insert_event`` inside the telemetry transaction. Only
    tool-call-shaped envelopes mutate state; everything else no-ops.
    """
    event_name = envelope.get("event_name")
    session_id = envelope.get("session_id")
    if not isinstance(event_name, str) or not isinstance(session_id, str):
        return
    event_time = str(envelope.get("event_time") or "")
    if event_name == _STARTED_EVENT_NAME:
        tool_use_id = envelope.get("tool_use_id")
        if isinstance(tool_use_id, str) and tool_use_id and event_time:
            record_tool_call_started(
                conn,
                session_id=session_id,
                tool_use_id=tool_use_id,
                tool_name=envelope.get("tool_name"),
                started_at=event_time,
                command_summary=_envelope_command_summary(envelope),
            )
        return
    if event_name in COMPLETION_EVENT_NAMES and event_time:
        tool_use_id = envelope.get("tool_use_id")
        record_tool_call_finished(
            conn,
            session_id=session_id,
            tool_use_id=tool_use_id if isinstance(tool_use_id, str) else None,
            tool_name=envelope.get("tool_name"),
            event_name=event_name,
            outcome=envelope.get("event_outcome"),
            completed_at=event_time,
            command_summary=_envelope_command_summary(envelope),
        )


__all__ = [
    "ACTIVITY_EVENT_NAMES",
    "COMMAND_SUMMARY_MAX_CHARS",
    "COMPLETION_EVENT_NAMES",
    "apply_envelope_state",
    "bump_session_tool_activity",
    "episode_column_present",
    "has_session_tool_calls_table",
    "record_tool_call_finished",
    "record_tool_call_started",
    "session_activity_columns_present",
    "truncate_command_summary",
]
