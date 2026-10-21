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
from yoke_core.domain.qa_plan_execution_abort_reason import (
    ABORT_REASON_MAX_LENGTH,
    REASON_DETAIL_SEPARATOR,
)
from yoke_core.domain.qa_plan_execution_abort_state import (
    abort_request,
    host_cleanup_proven,
    record_abort_request,
)
from yoke_core.domain.qa_plan_execution_authority import (
    PLAN_EXECUTION_STALE_SECONDS,
    plan_execution_is_stale,
)
from yoke_core.domain.qa_plan_execution_schema import TERMINAL_PLAN_EXECUTION_STATES
from yoke_core.domain.qa_plan_execution_store import (
    QaPlanExecutionStateError,
    lock_plan_execution,
)

#: The code a reconciled execution's release reason opens with.
RECONCILED_REASON = "qa-plan-operator-reconciled"


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


def _held_leases(conn: Any, execution: dict[str, Any]) -> list[Any]:
    from yoke_core.domain.coordination_claims import get_claim
    from yoke_core.domain.qa_plan_host_leases import execution_host_leases

    leases = {lease.id: lease for lease in execution_host_leases(conn, execution)}
    primary = execution.get("machine_lease_id")
    if primary is not None:
        claim = get_claim(conn, int(primary))
        if claim.is_active:
            leases[claim.id] = claim
    return sorted(leases.values(), key=lambda lease: int(lease.id))


def _recovery_request(conn: Any, execution: dict[str, Any], reason: str) -> dict:
    """Record cancellation, marked as reconcile's, so steering may reset hosts.

    An existing cancellation keeps its reason, ordinal and request time.
    """
    request = abort_request(execution)
    if request and request.get("reconcile"):
        return request
    if not request:
        detail = f"{RECONCILED_REASON}{REASON_DETAIL_SEPARATOR}{reason}"
        ordinal = min(int(execution["cursor_ordinal"]), len(execution["roster"]) - 1)
        request = {"reason": detail[:ABORT_REASON_MAX_LENGTH], "ordinal": ordinal}
    record_abort_request(conn, execution, {**request, "reconcile": True})
    conn.commit()
    return abort_request(execution)


def _reconcile_pending(execution: dict[str, Any]) -> bool:
    """Whether an earlier reconcile already recorded this cancellation.

    The reset that run asked for borrows the execution's lease and renews its
    heartbeat, so its retry cannot prove staleness again; the first run did.
    """
    return bool((abort_request(execution) or {}).get("reconcile"))


def _host_recovery_proven(conn: Any, execution: dict, request: dict) -> bool:
    from yoke_core.domain.agent_mission_restore import mission_restores_recorded

    ordinal = int(request["ordinal"])
    case = execution["roster"][ordinal]
    if case.get("runner_id") == "agent_mission" and mission_restores_recorded(
        conn, execution
    ):
        return True
    return host_cleanup_proven(conn, execution, ordinal)


def _host_recovery_refusal(
    execution: dict, request: dict, leases: list[Any], project: str
) -> QaPlanExecutionStateError:
    case = execution["roster"][int(request["ordinal"])]
    baseline = case.get("host_baseline")
    if baseline and case.get("starting_state") != "as_is":
        lead = "reset each held host to the interrupted case's declared baseline"
        steps = [
            f"yoke test-machine reset --project {project} --machine "
            f"{lease.target.machine_id} --baseline {baseline}"
            for lease in leases
        ]
    else:
        lead = (
            "release each held lease deliberately, because this case declares "
            "no baseline to reset to; manual release records the reset the "
            "next holder owes"
        )
        steps = [
            "yoke claims coordination-claim operator-release "
            + ("" if lease.key.startswith("QA_HOST:") else f"--project {project} ")
            + f"--key {lease.key} --claim-id {lease.id} --holder-session-id "
            f'{lease.session_id} --reason "<why>"'
            for lease in leases
        ]
    return QaPlanExecutionStateError(
        f"qa_reconcile_host_recovery_required: execution {execution['id']} still "
        f"holds lease(s) {', '.join(str(lease.id) for lease in leases)} and no "
        "host recovery is recorded. Cancellation is recorded, so a covering "
        f"steering seat may now {lead}: "
        + "; ".join(f"`{step}`" for step in steps)
        + f". Then retry `{reconcile_command(project, str(execution['id']))}`. "
        "Nothing else changed."
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
    session_id: str,
    reason: str,
) -> dict[str, Any]:
    """Settle one stranded execution and write its receipt atomically."""
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
    if (
        not terminal
        and not _reconcile_pending(execution)
        and not plan_execution_is_stale(execution)
    ):
        raise QaPlanExecutionStateError(
            f"qa_reconcile_execution_live: execution {execution_id} is still "
            f"reporting progress from session {execution.get('session_id')}. "
            "Stop a live walk with `yoke qa plan abort "
            f"{_subject_flag(conn, execution, project)} --execution-id "
            f"{execution_id} --reason TEXT`, or retry "
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
        leases = _held_leases(conn, execution)
        if leases:
            request = _recovery_request(conn, execution, reason)
            if not _host_recovery_proven(conn, execution, request):
                raise _host_recovery_refusal(execution, request, leases, project)
            from yoke_core.domain.coordination_claims import release

            for lease in leases:
                release(conn, int(lease.id), settle_reason, commit=False)
                released.append(int(lease.id))
        execution["machine_lease_id"] = None
    conn.execute(
        "UPDATE qa_plan_executions SET actor_id=%s,session_id=%s,"
        "machine_lease_id=%s WHERE id=%s",
        (actor_id, session_id, execution.get("machine_lease_id"), execution_id),
    )
    execution.update(actor_id=actor_id, session_id=session_id)
    hand_off = bundle_id is not None and (terminal or not abort_request(execution))
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
    if hand_off:
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
