"""Settle native wake attempts from the receipt they were sent to deliver.

A relay reports the native it started, never whether the envelope arrived.
Delivery happens inside the resumed turn, when a hook attaches the pending
message, so the only surface that can answer "did this wake work?" is the
receipt itself. Every attempt carrying an unverified transport observation
therefore stays open until this pass reads that receipt and closes it as
delivered, or as a resume that ran and delivered nothing.
"""

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
)
from yoke_contracts.session_control.wake_delivery import (
    NATIVE_RESUME_ACCEPTED_RESULT,
    TURN_WITHOUT_INJECTION_RECOVERY,
    TURN_WITHOUT_INJECTION_RESULT,
    WAKE_DELIVERED_RESULT,
    WAKE_DELIVERY_UNVERIFIED_RESULTS,
)
from yoke_core.domain import json_helper
from yoke_core.domain.organization_settings import OrganizationSettingsError
from yoke_core.domain.session_message_authorization import project_policy
from yoke_core.domain.session_message_types import (
    SessionMessageError,
    parse_timestamp,
    row_dict,
)
from yoke_core.domain.session_relay_storage import marker


EVENT_SESSION_WAKE_OUTCOME_RECORDED = "SessionWakeOutcomeRecorded"
WAKE_RECONCILIATION_ADAPTER_REVISION = "session-wake-reconciliation-v1"


def _after(value: object, boundary) -> object | None:
    observed = parse_timestamp(value)
    return observed if observed and observed > boundary else None


def _delivery_grace_seconds(
    conn: Any, project_id: int, cache: dict[int, int]
) -> int | None:
    """Seconds an undelivered envelope may wait before the route is judged.

    The same window the wake ladder waits before trying again: settling any
    sooner would name a wake undelivered while it is still the only one
    entitled to deliver. A project whose policy cannot be read leaves its
    attempts open rather than settling them against a guessed window; every
    receipt reached this table through that same policy, so in a live plane
    the lookup is already proven to resolve.
    """
    if project_id not in cache:
        try:
            policy = project_policy(conn, project_id)
        except (SessionMessageError, OrganizationSettingsError):
            return None
        cache[project_id] = int(policy.wake_ack_grace_seconds)
    return cache[project_id]


def _delivery_outcome(
    row: dict[str, Any], *, current, grace_seconds: int | None
) -> str | None:
    """Return this attempt's terminal verdict, or None while it is undecided."""
    started = parse_timestamp(row["started_at"])
    if started is None:
        return RESUME_NEVER_STARTED_RESULT
    # Injection is the whole job. An acknowledgement counts too: the receipt
    # cannot reach it without having been injected first, and a hook that
    # injected and acknowledged inside one turn may report only the later fact.
    if _after(row["last_injected_at"], started) or _after(
        row["acknowledged_at"], started
    ):
        return WAKE_DELIVERED_RESULT
    reported = str(row["result_code"] or "")
    if reported == NATIVE_RESUME_ACCEPTED_RESULT:
        # This transport hands the resume off and never reports again, so the
        # only bound left is the window an undelivered envelope may wait
        # before the wake ladder is entitled to try a different route.
        if grace_seconds is None:
            return None
        if current - started >= timedelta(seconds=grace_seconds):
            return TURN_WITHOUT_INJECTION_RESULT
        return None
    if reported == RESUMED_COMPLETED_RESULT:
        # The resume process exited. Whatever the turn did, it is over and the
        # envelope is still pending.
        return TURN_WITHOUT_INJECTION_RESULT
    posture_at = _after(row["turn_posture_at"], started)
    tool_at = _after(row["last_tool_call_at"], started)
    if row["turn_posture"] == "waiting" and posture_at is not None:
        return TURN_WITHOUT_INJECTION_RESULT
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


def _merged_evidence(
    raw: object,
    *,
    row: dict[str, Any],
    result_code: str,
    duration_ms: int,
) -> str:
    try:
        decoded = json_helper.loads_text(str(raw))
    except (TypeError, ValueError):
        decoded = None
    retained = redacted_evidence_document(decoded if isinstance(decoded, dict) else {})
    retained.update(
        redacted_evidence_document(
            {
                "result_code": result_code,
                "duration_ms": duration_ms,
                # The verdict overwrites the reported code, so the transport
                # observation is kept beside it. An undelivered wake whose
                # native accepted the resume is a different defect from one
                # whose native never came up.
                "transport_result": str(row["result_code"] or ""),
                "receipt_state": str(row["receipt_state"] or ""),
                "injection_count": int(row["injection_count"] or 0),
            }
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

    delivered = result_code == WAKE_DELIVERED_RESULT
    context = {
        "attempt_id": attempt_id,
        "message_id": message_id,
        "result_code": result_code,
    }
    if result_code == TURN_WITHOUT_INJECTION_RESULT:
        # An operator following this event is looking at the only record of a
        # wake that reported nothing wrong and delivered nothing.
        context["recovery"] = TURN_WITHOUT_INJECTION_RECOVERY
    emit_event(
        EVENT_SESSION_WAKE_OUTCOME_RECORDED,
        event_kind="system",
        event_type="session_wake",
        source_type="backend",
        session_id=session_id,
        severity="INFO" if delivered else "WARN",
        outcome=("completed" if delivered else "failed"),
        context=context,
        created_at=now,
        conn=conn,
    )


def reconcile_spawned_wake_attempts(conn: Any, *, now: str) -> int:
    """Close wake attempts whose receipt now proves delivery or its absence."""
    current = parse_timestamp(now)
    if current is None:
        return 0
    p = marker(conn)
    unverified = tuple(sorted(WAKE_DELIVERY_UNVERIFIED_RESULTS))
    rows = conn.execute(
        "SELECT a.attempt_id,a.message_id,a.target_session_id,a.started_at,"
        "a.evidence,a.result_code,hs.project_id,hs.turn_posture,"
        "hs.turn_posture_at,hs.last_tool_call_at,r.state AS receipt_state,"
        "r.injection_count,r.last_injected_at,r.acknowledged_at "
        "FROM session_message_attempts a JOIN harness_sessions hs "
        "ON hs.session_id=a.target_session_id "
        "LEFT JOIN session_message_recipients r ON r.message_id=a.message_id "
        "AND r.session_id=a.target_session_id "
        "WHERE a.completed_at IS NULL AND a.result_code IN ("
        + ",".join(p for _ in unverified)
        + ") ORDER BY a.started_at,a.attempt_id",
        unverified,
    ).fetchall()
    changed = 0
    grace_cache: dict[int, int] = {}
    for raw in rows:
        row = row_dict(raw)
        settled = _delivery_outcome(
            row,
            current=current,
            grace_seconds=_delivery_grace_seconds(
                conn, int(row["project_id"]), grace_cache
            ),
        )
        if settled is None:
            continue
        started = parse_timestamp(row["started_at"]) or current
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
                settled,
                WAKE_RECONCILIATION_ADAPTER_REVISION,
                _merged_evidence(
                    row["evidence"],
                    row=row,
                    result_code=settled,
                    duration_ms=duration_ms,
                ),
                row["attempt_id"],
                row["result_code"],
            ),
        )
        if cursor.rowcount != 1:
            continue
        changed += 1
        _emit_outcome(
            conn,
            attempt_id=str(row["attempt_id"]),
            message_id=str(row["message_id"]),
            session_id=str(row["target_session_id"]),
            result_code=settled,
            now=now,
        )
    return changed


__all__ = [
    "EVENT_SESSION_WAKE_OUTCOME_RECORDED",
    "WAKE_RECONCILIATION_ADAPTER_REVISION",
    "reconcile_spawned_wake_attempts",
]
