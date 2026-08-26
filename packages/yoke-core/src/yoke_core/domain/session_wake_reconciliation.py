"""Settle detached resume attempts from first-class session hook state."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from yoke_contracts.session_control.evidence import redacted_evidence_document
from yoke_contracts.session_control.resume import (
    RESUME_INACTIVITY_SECONDS,
    RESUME_NEVER_STARTED_RESULT,
    RESUME_RUNAWAY_RESULT,
    RESUME_RUNAWAY_SECONDS,
    RESUMED_COMPLETED_RESULT,
    RESUMED_DIED_RESULT,
    RESUMED_RUNNING_RESULT,
)
from yoke_core.domain import json_helper
from yoke_core.domain.session_message_types import parse_timestamp
from yoke_core.domain.session_relay_storage import marker


EVENT_SESSION_WAKE_OUTCOME_RECORDED = "SessionWakeOutcomeRecorded"
WAKE_RECONCILIATION_ADAPTER_REVISION = "session-wake-reconciliation-v1"


def _after(value: object, boundary) -> object | None:
    observed = parse_timestamp(value)
    return observed if observed and observed > boundary else None


def _outcome(row: Any, *, current) -> str | None:
    started = parse_timestamp(row[3])
    if started is None:
        return RESUME_NEVER_STARTED_RESULT
    posture_at = _after(row[6], started)
    tool_at = _after(row[7], started)
    if row[5] == "waiting" and posture_at is not None:
        return RESUMED_COMPLETED_RESULT
    latest_activity = max(
        (value for value in (posture_at, tool_at) if value is not None),
        default=None,
    )
    if current - started >= timedelta(seconds=RESUME_RUNAWAY_SECONDS):
        return RESUME_RUNAWAY_RESULT
    inactivity = timedelta(seconds=RESUME_INACTIVITY_SECONDS)
    if latest_activity is not None and current - latest_activity >= inactivity:
        return RESUMED_DIED_RESULT
    if latest_activity is None and current - started >= inactivity:
        return RESUME_NEVER_STARTED_RESULT
    return None


def _merged_evidence(raw: object, *, result_code: str, duration_ms: int) -> str:
    try:
        decoded = json_helper.loads_text(str(raw))
    except (TypeError, ValueError):
        decoded = None
    retained = redacted_evidence_document(decoded if isinstance(decoded, dict) else {})
    retained.update(
        redacted_evidence_document(
            {"result_code": result_code, "duration_ms": duration_ms}
        )
    )
    return json_helper.dumps_compact(retained)


def _emit_outcome(
    conn: Any,
    *,
    attempt_id: str,
    message_id: str,
    session_id: str,
    result_code: str,
    now: str,
) -> None:
    from yoke_core.domain.events import emit_event

    emit_event(
        EVENT_SESSION_WAKE_OUTCOME_RECORDED,
        event_kind="system",
        event_type="session_wake",
        source_type="backend",
        session_id=session_id,
        severity="INFO" if result_code == RESUMED_COMPLETED_RESULT else "WARN",
        outcome=("completed" if result_code == RESUMED_COMPLETED_RESULT else "failed"),
        context={
            "attempt_id": attempt_id,
            "message_id": message_id,
            "result_code": result_code,
        },
        created_at=now,
        conn=conn,
    )


def reconcile_spawned_wake_attempts(conn: Any, *, now: str) -> int:
    """Close detached resumes whose target session now proves an outcome."""
    current = parse_timestamp(now)
    if current is None:
        return 0
    p = marker(conn)
    rows = conn.execute(
        "SELECT a.attempt_id,a.message_id,a.target_session_id,a.started_at,"
        "a.evidence,hs.turn_posture,hs.turn_posture_at,hs.last_tool_call_at "
        "FROM session_message_attempts a JOIN harness_sessions hs "
        "ON hs.session_id=a.target_session_id "
        "WHERE a.completed_at IS NULL AND a.result_code="
        + p
        + " ORDER BY a.started_at,a.attempt_id",
        (RESUMED_RUNNING_RESULT,),
    ).fetchall()
    changed = 0
    for row in rows:
        settled = _outcome(row, current=current)
        if settled is None:
            continue
        result_code = settled
        started = parse_timestamp(row[3]) or current
        duration_ms = min(
            3_600_000,
            max(0, int((current - started).total_seconds() * 1000)),
        )
        cursor = conn.execute(
            "UPDATE session_message_attempts SET completed_at="
            + p
            + ",result_code="
            + p
            + ",adapter_revision=COALESCE(adapter_revision,"
            + p
            + ")"
            + ",evidence="
            + p
            + f" WHERE attempt_id={p} AND completed_at IS NULL "
            "AND result_code=" + p,
            (
                now,
                result_code,
                WAKE_RECONCILIATION_ADAPTER_REVISION,
                _merged_evidence(
                    row[4], result_code=result_code, duration_ms=duration_ms
                ),
                row[0],
                RESUMED_RUNNING_RESULT,
            ),
        )
        if cursor.rowcount != 1:
            continue
        changed += 1
        _emit_outcome(
            conn,
            attempt_id=str(row[0]),
            message_id=str(row[1]),
            session_id=str(row[2]),
            result_code=result_code,
            now=now,
        )
    return changed


__all__ = [
    "EVENT_SESSION_WAKE_OUTCOME_RECORDED",
    "WAKE_RECONCILIATION_ADAPTER_REVISION",
    "reconcile_spawned_wake_attempts",
]
