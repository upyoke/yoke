"""Pause and re-enter a durable QA cursor without releasing its custody."""

from __future__ import annotations

import json
from typing import Any

from yoke_core.domain.qa_plan_execution_store import (
    QaPlanExecutionStateError,
    canonical,
    marker,
    plan_execution_view,
)
from yoke_core.domain.qa_plan_execution_target_snapshot import require_execution_target

PAUSE_REASON = "qa-communication-outcome-unknown:"


def checkin_view(execution):
    from yoke_core.domain.qa_plan_execution_abort_state import abort_request

    return {
        "abort_requested": abort_request(execution) is not None,
        "execution_id": str(execution["id"]),
        **{
            key: execution.get(key)
            for key in (
                "state",
                "cursor_ordinal",
                "roster_digest",
                "execution_target_digest",
                "machine_lease_id",
                "heartbeat_at",
            )
        },
    }


def require_execution_custody(conn, execution):
    """Validate issued leases before any renewal; never revive lost custody."""
    from yoke_core.domain.machine_qa_execution_protocol import _validate_lease_owner
    from yoke_core.domain.qa_plan_host_leases import execution_host_leases

    lease_ids = {claim.id for claim in execution_host_leases(conn, execution)}
    if execution.get("machine_lease_id") is not None:
        lease_ids.add(int(execution["machine_lease_id"]))
    if not lease_ids:
        return
    project = str(execution["roster"][0]["project"])
    for lease_id in sorted(lease_ids):
        _validate_lease_owner(
            conn,
            project=project,
            session_id=str(execution["session_id"]),
            actor_id=execution.get("actor_id"),
            lease_id=lease_id,
            allow_released=False,
        )
    cursor = int(execution["cursor_ordinal"])
    if cursor < len(execution["roster"]):
        from yoke_core.domain.qa_plan_host_leases import require_case_host_leases

        require_case_host_leases(conn, execution, execution["roster"][cursor])


def pause_execution(
    conn,
    execution,
    *,
    phase,
    cursor,
    request_id,
    attempts,
    evidence_path=None,
    capture_path=None,
):
    if execution["state"] not in {"active", "waiting"}:
        raise QaPlanExecutionStateError(
            "qa_pause_terminal: preserve terminal history; communication cannot revive it"
        )
    require_execution_target(execution)
    if phase == "checkin" and int(execution["cursor_ordinal"]) != cursor:
        raise QaPlanExecutionStateError(
            "qa_pause_cursor_changed: inspect the durable cursor before re-entry; this receipt belongs to an earlier checkpoint"
        )
    evidence = canonical(
        {
            "phase": phase,
            "cursor": cursor,
            "request_id": request_id,
            "attempts": attempts,
            "evidence_path": evidence_path,
            "capture_path": capture_path,
        }
    )
    prior = str(execution.get("release_reason") or "")
    if prior.startswith(PAUSE_REASON):
        previous = json.loads(prior[len(PAUSE_REASON) :])
        if previous.get("request_id") == request_id and previous.get("resumed"):
            raise QaPlanExecutionStateError(
                "qa_recovery_receipt_consumed: this pause already resumed; inspect the current action outcome instead of reusing its receipt"
            )
        current = json.loads(evidence)
        if previous.get("attempts"):
            current["first_failure"] = previous.get("first_failure", previous)
        evidence = canonical(current)
    reason = PAUSE_REASON + evidence
    p = marker(conn)
    conn.execute(
        f"UPDATE qa_plan_executions SET state='waiting',release_reason={p} WHERE id={p}",
        (reason, str(execution["id"])),
    )
    conn.commit()
    execution.update(state="waiting", release_reason=reason)
    return checkin_view(execution)


def resume_execution(conn: Any, execution: dict) -> dict:
    if execution["state"] not in {"active", "waiting", "awaiting_agent_review"}:
        raise QaPlanExecutionStateError(
            "qa_resume_terminal: preserve terminal history; this execution cannot resume"
        )
    require_execution_target(execution)
    reason = str(execution.get("release_reason") or "")
    evidence = (
        json.loads(reason[len(PAUSE_REASON) :])
        if reason.startswith(PAUSE_REASON)
        else None
    )
    if evidence is not None and not evidence.get("resumed"):
        if evidence["phase"] != "checkin" and int(execution["cursor_ordinal"]) <= int(
            evidence["cursor"]
        ):
            raise QaPlanExecutionStateError(
                "qa_action_outcome_unknown: the case has not durably advanced; inspect "
                "its saved request and capture before recording its exact result. "
                "Do not reset the host or replay the action"
            )
    else:
        cursor = int(execution["cursor_ordinal"])
        if evidence is not None and evidence.get("case_inflight") == cursor:
            raise QaPlanExecutionStateError(
                "qa_pause_unconfirmed: a case may have started at this cursor; "
                "use the saved pre-case check-in --recovery-file to confirm its pause, "
                "or reconcile its saved action/recording outcome without replay"
            )
        if execution["state"] == "active" and cursor < len(execution["roster"]):
            requirement_id = int(execution["roster"][cursor]["requirement_id"])
            captured = conn.execute(
                "SELECT 1 FROM qa_runs WHERE qa_requirement_id=%s AND created_at >= %s LIMIT 1",
                (requirement_id, execution["created_at"]),
            ).fetchone()
            if execution.get("machine_lease_id") is not None or captured is not None:
                raise QaPlanExecutionStateError(
                    "qa_action_outcome_unknown: active custody or a capture exists without "
                    "a confirmed safe pause; inspect and record the saved case outcome "
                    "before re-entry, without resetting or replaying actions"
                )
    require_execution_custody(conn, execution)
    if execution["state"] == "waiting":
        p = marker(conn)
        conn.execute(
            f"UPDATE qa_plan_executions SET state='active' WHERE id={p}",
            (str(execution["id"]),),
        )
        execution["state"] = "active"
    if evidence is not None:
        evidence["resumed"] = True
        reason = PAUSE_REASON + canonical(evidence)
        conn.execute(
            "UPDATE qa_plan_executions SET release_reason=%s WHERE id=%s",
            (reason, str(execution["id"])),
        )
        execution["release_reason"] = reason
    conn.commit()
    return plan_execution_view(conn, execution)


def resume_if_paused(conn, execution):
    if not str(execution.get("release_reason") or "").startswith(PAUSE_REASON):
        return False
    resume_execution(conn, execution)
    return True


def bound_checkin_queries(conn):
    from yoke_core.domain.db_backend import connection_is_postgres

    if connection_is_postgres(conn):
        conn.execute("SELECT set_config('lock_timeout', '2000ms', true)")
        conn.execute("SELECT set_config('statement_timeout', '5000ms', true)")


def inflight_checkpoint(execution):
    reason = str(execution.get("release_reason") or "")
    evidence = (
        json.loads(reason[len(PAUSE_REASON) :])
        if reason.startswith(PAUSE_REASON)
        else {}
    )
    evidence.update(resumed=True, case_inflight=int(execution["cursor_ordinal"]))
    return PAUSE_REASON + canonical(evidence)
