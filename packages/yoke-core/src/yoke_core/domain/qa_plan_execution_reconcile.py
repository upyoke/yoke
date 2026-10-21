"""A steering seat settles a QA plan execution its owner can no longer settle.

An execution strands when its owning session ended, or its recovery receipt
was lost, while it still holds review work or host custody. Abort needs the
owner's runner, adoption needs a live claim on the item, and manual host
release needs an active lease, so a stranded row can outlive all three.
Reconciliation is the operator path: a covering steering seat names the
execution and a reason. A host lease still held is released only after its
recovery is proven; a pending review passes to the caller; anything else
settles as aborted with no verdict. One receipt row records who, why and the
prior state, committed with the settlement.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from yoke_core.domain.db_helpers import instant_parameter, query_one, utc_now
from yoke_core.domain.qa_plan_execution_abort_reason import REASON_DETAIL_SEPARATOR
from yoke_core.domain.qa_plan_execution_abort_state import abort_request
from yoke_core.domain.qa_plan_execution_reconcile_hosts import (
    RECONCILED_REASON,
    held_leases,
    host_recovery_proven,
    host_recovery_refusal,
    reconcile_pending,
    recovery_request,
)
from yoke_core.domain.qa_plan_execution_authority import (
    PLAN_EXECUTION_STALE_SECONDS,
    owning_session_is_parked,
    plan_execution_is_stale,
)
from yoke_core.domain.qa_plan_execution_schema import TERMINAL_PLAN_EXECUTION_STATES
from yoke_core.domain.qa_plan_execution_store import (
    QaPlanExecutionStateError,
    lock_plan_execution,
)


def reconcile_command(project: str, execution_id: str) -> str:
    """The exact operator command that settles this execution."""
    return (
        f"yoke qa plan reconcile --project {project} --execution-id "
        f'{execution_id} --reason "<why its owner cannot settle it>"'
    )


def execution_project(conn: Any, execution: dict[str, Any]) -> tuple[int, str]:
    """The project id and slug whose steering seat may reconcile this row."""
    from yoke_core.domain.function_target_row_project import slug_for_project_id
    from yoke_core.domain.qa_plan_execution_stop import execution_project_id

    project_id = execution_project_id(conn, execution)
    return project_id, slug_for_project_id(conn, project_id)


def _pending_bundle_id(conn: Any, execution_id: str) -> str | None:
    row = query_one(
        conn,
        "SELECT id FROM qa_plan_review_bundles "
        "WHERE execution_id=%s AND state='pending'",
        (execution_id,),
    )
    return None if row is None else str(row["id"])


def _valid_capture(conn: Any, bundle_id: str) -> bool:
    """Whether the pending review has at least one capture a reviewer can judge.

    A case without artifacts, or one its runner marked degraded (a mission
    whose walker never attached proof), gives a reviewer nothing to read.
    """
    from yoke_core.domain.qa_mission_stop_settlement import mission_review_cases
    from yoke_core.domain.qa_plan_review import _json_object

    row = query_one(
        conn, "SELECT bundle_json FROM qa_plan_review_bundles WHERE id=%s", (bundle_id,)
    )
    cases = mission_review_cases(
        conn, _json_object(row["bundle_json"]).get("cases") or []
    )
    return any(
        case.get("artifacts") and not case.get("capture_degraded_reason")
        for case in cases
    )


def _close_unreviewable(conn: Any, bundle_id: str, actor_id, session_id) -> None:
    """Close a review with no judgeable capture; it records no verdict."""
    conn.execute(
        "UPDATE qa_plan_review_bundles SET state='completed',reviewer_actor_id=%s,"
        "reviewer_session_id=%s,reviewed_at=%s WHERE id=%s AND state='pending'",
        (actor_id, session_id, instant_parameter(conn, utc_now()), bundle_id),
    )


def _subject_flag(conn: Any, execution: dict, project: str) -> str:
    """The subject flag abort and review-begin take for this execution."""
    from yoke_core.domain.qa_pending_agent_review import review_scope_flag

    flag = review_scope_flag(conn, execution)
    return f"--project {project}" if flag == "--project PROJECT" else flag


def reconcile_execution(
    conn: Any,
    execution_id: str,
    *,
    project_id: int,
    actor_id: str | None,
    session_id: str | None,
    reason: str,
) -> dict[str, Any]:
    """Settle one stranded execution and write its receipt atomically.

    A session-less control-plane operator may settle but cannot take over a
    review, because review-begin needs an owning session.
    """
    execution = lock_plan_execution(conn, execution_id)
    owner_project_id, project = execution_project(conn, execution)
    if owner_project_id != int(project_id):
        raise QaPlanExecutionStateError(
            f"qa_reconcile_project_mismatch: execution {execution_id} belongs to "
            f"project {project}; rerun with --project {project}. Nothing changed."
        )
    state = str(execution["state"])
    terminal = state in TERMINAL_PLAN_EXECUTION_STATES
    bundle_id = _pending_bundle_id(conn, execution_id)
    if terminal and bundle_id is None:
        raise QaPlanExecutionStateError(
            f"qa_reconcile_already_settled: execution {execution_id} is already "
            f"{state} with no pending review; there is nothing to reconcile."
        )
    flag = _subject_flag(conn, execution, project)
    if state == "active":
        raise QaPlanExecutionStateError(
            f"qa_reconcile_runner_driven: execution {execution_id} is active, so "
            "its runner may still be driving the host; reconciliation never "
            "settles a runner-driven walk. Stop it with `yoke qa plan abort "
            f"{flag} --execution-id {execution_id} --reason TEXT`: a steering "
            "seat's abort records a stop its runner obeys, and once silent for "
            f"{PLAN_EXECUTION_STALE_SECONDS // 60} minutes any session may "
            "abandon it. Nothing changed."
        )
    # A parked owner holds an unfinished walk; an ended walk's review is not
    # held by the park, so only the former refuses.
    if not terminal and owning_session_is_parked(conn, execution):
        raise QaPlanExecutionStateError(
            f"qa_reconcile_owner_parked: session {execution.get('session_id')} "
            f"is parked and still holds execution {execution_id}. Ask it to "
            "unpark and settle its own walk, or end that session, then retry. "
            "Nothing changed."
        )
    if (
        not terminal
        and not reconcile_pending(execution)
        and not plan_execution_is_stale(execution)
    ):
        raise QaPlanExecutionStateError(
            f"qa_reconcile_execution_live: execution {execution_id} is still "
            f"reporting progress from session {execution.get('session_id')}. "
            "Stop a live walk with `yoke qa plan abort "
            f"{flag} --execution-id {execution_id} --reason TEXT`, or retry "
            f"reconciliation after {PLAN_EXECUTION_STALE_SECONDS // 60} minutes "
            "without a heartbeat. Nothing changed."
        )
    reconciliation_id = str(uuid4())
    settle_reason = (
        f"{RECONCILED_REASON}{REASON_DETAIL_SEPARATOR}"
        f"reconciliation {reconciliation_id}"
    )
    prior = (state, execution.get("actor_id"), execution.get("session_id"))
    released: list[int] = []
    if not terminal:
        hosts, review_leases = held_leases(conn, execution)
        if hosts:
            request = recovery_request(conn, execution, reason)
            if not host_recovery_proven(conn, execution, request):
                raise host_recovery_refusal(
                    execution,
                    request,
                    hosts,
                    project,
                    reconcile_command(project, execution_id),
                )
        if bundle_id is None and any(
            case.get("verdict_path") == "agent" for case in execution["roster"]
        ):
            from yoke_core.domain.qa_plan_review import begin_plan_review

            begin_plan_review(conn, execution, completed_captures_only=True)
            bundle_id = _pending_bundle_id(conn, execution_id)
    hand_off = bundle_id is not None and _valid_capture(conn, bundle_id)
    if hand_off and not session_id:
        conn.rollback()
        raise QaPlanExecutionStateError(
            f"qa_reconcile_review_needs_session: execution {execution_id} has a "
            "judgeable capture, and handing its review over assigns it to a "
            "session. Rerun from a session holding a steering seat covering "
            f"project {project}. Nothing changed."
        )
    if not terminal:
        from yoke_core.domain.coordination_claims import release

        for lease in hosts + review_leases:
            release(conn, int(lease.id), settle_reason, commit=False)
            released.append(int(lease.id))
        execution["machine_lease_id"] = None
    if bundle_id is not None and not hand_off:
        _close_unreviewable(conn, bundle_id, actor_id, session_id)
    owner = (actor_id, session_id) if session_id else (prior[1], prior[2])
    conn.execute(
        "UPDATE qa_plan_executions SET actor_id=%s,session_id=%s,"
        "machine_lease_id=%s WHERE id=%s",
        (*owner, execution.get("machine_lease_id"), execution_id),
    )
    execution.update(actor_id=owner[0], session_id=owner[1])
    outcome = "review_handoff" if hand_off else "aborted"
    conn.execute(
        "INSERT INTO qa_plan_execution_reconciliations "
        "(id,execution_id,actor_id,session_id,reason,outcome,prior_state,"
        "prior_actor_id,prior_session_id,released_lease_ids,reconciled_at) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            reconciliation_id,
            execution_id,
            actor_id,
            session_id,
            reason,
            outcome,
            *prior,
            json.dumps(released),
            instant_parameter(conn, utc_now()),
        ),
    )
    if terminal or (hand_off and not abort_request(execution)):
        conn.commit()
    else:
        from yoke_core.domain.qa_plan_execution_lifecycle import finish_plan_execution

        finish_plan_execution(conn, execution, state="aborted", reason=settle_reason)
    bundle_id = _pending_bundle_id(conn, execution_id)
    return {
        "execution_id": execution_id,
        "reconciliation_id": reconciliation_id,
        "outcome": outcome,
        "state": str(execution["state"]),
        "prior_state": state,
        "prior_session_id": prior[2],
        "released_lease_ids": released,
        "review_bundle_id": bundle_id,
        "next_command": (
            f"yoke qa plan review-begin {_subject_flag(conn, execution, project)} "
            f"--execution-id {execution_id}"
            if bundle_id
            else None
        ),
    }


__all__ = [
    "RECONCILED_REASON",
    "execution_project",
    "reconcile_command",
    "reconcile_execution",
]
