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

from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _get_columns as _schema_get_columns
from yoke_core.domain.session_recovery_facts import stamp_completed_work
from yoke_core.domain.session_tool_call_start_reconcile import (
    adopt_earlier_start,
)

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
#: The one completion that proves the session did work, as opposed to
#: attempting it. Launch settlement reads the marker this stamps.
_COMPLETED_EVENT_NAME = "HarnessToolCallCompleted"
_TOOL_ACTIVITY_EVENT_NAMES = frozenset((_STARTED_EVENT_NAME, *COMPLETION_EVENT_NAMES))


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


def session_mode_column_present(conn: Any) -> bool:
    """True when the connected schema carries the declared session posture."""
    return "mode" in _columns(conn, "harness_sessions")


def native_thread_id_column_present(conn: Any) -> bool:
    """True when the connected schema carries the Codex native-thread mapping.

    Many test fixtures compose ``harness_sessions`` by hand rather than
    through the real schema converge (``episode_started_at`` tolerates the
    same gap); introspecting here lets registration degrade gracefully on
    those minimal schemas instead of requiring every one of them to track
    every column the real production table carries.
    """
    return "native_thread_id" in _columns(conn, "harness_sessions")


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
    """Open a ``session_tool_calls`` row, or give an existing one its start.

    A start that lost the race to its own completion meets a row already
    there, and dropping it discarded the call's only captured start. It is
    reconciled instead by
    :func:`yoke_core.domain.session_tool_call_start_reconcile.adopt_earlier_start`,
    which corrects that one endpoint without reopening the call. Activity is
    counted by the completion alone, so no arrival order recounts a call, and
    a duplicate or replayed start changes nothing.
    """
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
    if getattr(cursor, "rowcount", 0) > 0:
        return True
    return adopt_earlier_start(
        conn,
        placeholder=p,
        session_id=session_id,
        tool_use_id=tool_use_id,
        started_at=started_at,
    )


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
) -> bool:
    """Close the open row, bump activity, and report whether it closed now.

    A completion without a prior Started row (the pre-hook dropped the
    payload, or the call predates the table) inserts a closed row so the
    lint guardrails and counts stay coherent. ``bump_activity`` bumps
    ``last_tool_call_at`` / ``tool_call_count`` only for
    :data:`ACTIVITY_EVENT_NAMES` — the orphan sweep's synthesized
    interrupted completions pass ``bump_activity=False`` because the
    session is ending and sweep time is not agent activity.

    **The bump is conditional on this call actually closing the row.**
    The resident retries a batch whose later observation failed, so the
    earlier ones arrive a second time; counting each arrival rather than
    each completion inflated ``tool_call_count`` and could drag
    ``last_tool_call_at`` backwards to a replayed stamp — and
    ``last_tool_call_at`` is what the idle sweep, the claim-freshness
    check, and the vendor-resume budget all read. The call identity
    ``(session_id, tool_use_id)`` already distinguishes a new completion
    from a re-delivered one, so the state transition decides, not the
    arrival.

    A caller with no ``tool_use_id``, or a fixture with no
    ``session_tool_calls`` table, has no identity to deduplicate on and
    keeps the unconditional bump: there, an arrival is the only evidence
    a completion exists.
    """
    if not session_id:
        return False
    p = _p(conn)
    transitioned = True
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
        transitioned = getattr(cursor, "rowcount", 0) > 0
        if not transitioned:
            inserted = conn.execute(
                "INSERT INTO session_tool_calls "
                "(session_id, tool_use_id, tool_name, started_at, "
                " completed_at, outcome, command_summary) "
                f"VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}) "
                "ON CONFLICT(session_id, tool_use_id) DO NOTHING",
                (
                    session_id,
                    tool_use_id,
                    tool_name,
                    completed_at,
                    completed_at,
                    outcome,
                    summary,
                ),
            )
            transitioned = getattr(inserted, "rowcount", 0) > 0
    if not transitioned:
        return False
    if bump_activity and event_name in ACTIVITY_EVENT_NAMES:
        bump_session_tool_activity(
            conn,
            session_id=session_id,
            at=completed_at,
        )
    if bump_activity and event_name == _COMPLETED_EVENT_NAME:
        stamp_completed_work(conn, session_id, completed_at)
    return True


def bump_session_tool_activity(conn: Any, *, session_id: str, at: str) -> None:
    """Stamp ``last_tool_call_at`` and increment ``tool_call_count``.

    The stamp only ever moves forward. An observation can arrive out of
    order — the resident batches them and retries — and every reader of
    this column treats it as "the last time this session did anything",
    so an older stamp overwriting a newer one manufactures idleness that
    never happened.
    """
    if not session_activity_columns_present(conn):
        return
    p = _p(conn)
    conn.execute(
        "UPDATE harness_sessions "
        "SET last_tool_call_at = CASE WHEN last_tool_call_at IS NULL "
        f"    OR last_tool_call_at < {p} THEN {p} ELSE last_tool_call_at END, "
        "    tool_call_count = COALESCE(tool_call_count, 0) + 1 "
        f"WHERE session_id = {p}",
        (at, at, session_id),
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
    observed_at = None
    if event_time and event_name in _TOOL_ACTIVITY_EVENT_NAMES:
        try:
            observed_at = datetime.fromisoformat(event_time.replace("Z", "+00:00"))
        except ValueError:
            observed_at = None
    if observed_at is not None:
        from yoke_core.domain.session_turn_posture import stamp_turn_posture

        stamp_turn_posture(
            conn,
            session_id=session_id,
            posture="running",
            observed_at=observed_at,
        )
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
    "native_thread_id_column_present",
    "session_mode_column_present",
    "record_tool_call_finished",
    "record_tool_call_started",
    "session_activity_columns_present",
    "truncate_command_summary",
]
