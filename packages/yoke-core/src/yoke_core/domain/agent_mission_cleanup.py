"""Owner-only host custody after a walk is stopped or its run ends.

An abort or member removal leaves a walk holding its machine live under a
recorded abort; its walk-end teardown is the cleanup proof, so finishing it
releases the host and settles that abort in one transaction.
"""

from __future__ import annotations

import base64
import json
from typing import Any

from yoke_contracts.api.function_call import HandlerOutcome, TargetRef
from yoke_core.domain.qa_plan_execution_abort_reason import (
    MEMBER_REMOVED_REASON,
    member_removal_pending,
    member_removed,
)
from yoke_core.domain.agent_mission_cleanup_docket import cleanup_mission, original_host
from yoke_core.domain.qa_case_host_custody import bind_case_host, case_host_lease_id
from yoke_core.domain.qa_plan_execution_store import same_owner


def cleanup_execution(conn: Any, execution: dict) -> bool:
    from yoke_core.domain.qa_deployment_execution_cleanup import terminal_run_status

    from yoke_core.domain.qa_plan_execution_abort_state import mission_abort_pending

    return (
        member_removed(execution)
        or member_removal_pending(execution)
        or mission_abort_pending(execution)
        or bool(terminal_run_status(conn, execution))
    )


def cleanup_request(request: Any) -> bool:
    return request.function == "test_machine.mission.access" and (
        request.payload or {}
    ).get("cleanup") in ("begin", "finish")


def cleanup_authority(conn: Any, request: Any, execution: dict) -> bool:
    """An ended deployment grants only its original session teardown."""
    from yoke_core.domain.qa_plan_execution_authority import (
        require_plan_execution_subject,
    )

    if not cleanup_request(request) or not cleanup_execution(conn, execution):
        return False
    from yoke_core.domain.qa_execution_request_identity import resolve_execution_request

    request = resolve_execution_request(conn, request, execution)
    require_plan_execution_subject(
        execution,
        item_id=request.target.item_id,
        deployment_run_id=request.target.deployment_run_id,
    )
    return same_owner(
        execution, actor_id=request.actor.actor_id, session_id=request.actor.session_id
    )


def cleanup_claim_authority(request: Any) -> bool:
    if not cleanup_request(request):
        return False
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.qa_plan_execution_store import select_plan_execution

    conn = connect()
    try:
        execution = select_plan_execution(
            conn, request.payload.get("execution_id"), lock=False
        )
        return cleanup_authority(conn, request, execution)
    except (LookupError, ValueError):
        return False
    finally:
        conn.close()


def _unsettled(execution: dict | None) -> str:
    """What a rolled-back walk-end left in place."""
    if execution is None:
        return "Nothing settled: the walk-end rolled back before reading its execution."
    lease = execution.get("test_machine_lease_id")
    held = (
        "no cleanup lease is held"
        if lease is None
        else f"cleanup lease {lease} is still held"
    )
    return (
        f"Nothing settled: {held} and execution {execution['id']} is still "
        f"{execution['state']}."
    )


def _store_restore(
    conn: Any, request: Any, parsed: Any, execution: dict, run_id: int
) -> HandlerOutcome | None:
    """Record the restore receipt in the caller's locked transaction."""
    from yoke_core.domain.machine_qa_outcomes import _failure
    from yoke_core.domain.machine_qa_submission_artifacts import (
        ensure_secret_free_result,
    )
    from yoke_core.domain.qa_artifact_recording import record_qa_artifact
    from yoke_contracts.refusal_recovery import compose_refusal

    try:
        ensure_secret_free_result(parsed.restore)
    except ValueError as exc:
        cause, fix = str(exc), "remove that field from the restore receipt"
    else:
        artifact_request = request.model_copy(
            update={
                "function": "qa.artifact.add",
                "target": TargetRef(
                    kind="qa_requirement", qa_requirement_id=parsed.requirement_id
                ),
                "payload": {
                    "run_id": run_id,
                    "artifact_type": "starting_state_restore",
                    "filename": "starting-state-restore.json",
                    "content_type": "application/json",
                    "content_base64": base64.b64encode(
                        json.dumps(parsed.restore, sort_keys=True).encode()
                    ).decode(),
                },
            }
        )
        stored = record_qa_artifact(conn, artifact_request, locked_execution=execution)
        if stored.primary_success:
            return None
        cause = f"{stored.error.code}: {stored.error.message}"
        fix = "fix the named artifact storage cause"
    return _failure(
        "mission_restore_evidence_failed",
        compose_refusal(
            f"mission_restore_evidence_failed: {cause}. {_unsettled(execution)}",
            recovery=f"{fix}, then rerun the same yoke qa mission walk-end; it "
            "records the restore, releases the lease and settles the execution",
        ),
    )


def _finish(
    conn: Any, request: Any, parsed: Any, execution: dict, run_id: int
) -> HandlerOutcome | None:
    from yoke_core.domain.coordination_claims import get_claim

    ordinal, case, _ = cleanup_mission(conn, execution, parsed.requirement_id)
    lease_id = case_host_lease_id(conn, execution, case)
    if lease_id is None or parsed.lease_id != lease_id:
        raise ValueError(
            "mission_cleanup_lease_mismatch: rerun walk-end to acquire cleanup custody"
        )
    lease = get_claim(conn, lease_id)
    if lease.session_id != request.actor.session_id:
        raise ValueError(
            "mission_cleanup_owner_required: cleanup lease belongs to another session"
        )
    if parsed.restore is not None:
        refusal = _store_restore(conn, request, parsed, execution, run_id)
        if refusal is not None:
            conn.rollback()
            return refusal
    from yoke_core.domain.machine_reset_debt import record_reset_owed
    from yoke_core.domain.qa_plan_abort_reset import walk_reset_proven
    from yoke_core.domain.qa_plan_execution_abort_state import case_restore_proven

    proven = case_restore_proven(case, parsed.restore or {}) or walk_reset_proven(
        conn, execution, case, lease.id
    )
    if parsed.restore is None and not proven:
        raise ValueError(
            "mission_cleanup_restore_unproven: walk-end sent no restore receipt "
            "and this lease has no verified reset to the case's declared baseline "
            "after cancellation"
        )
    if not proven:
        record_reset_owed(
            conn, case=case, test_machine=lease.target.test_machine, lease_id=lease.id
        )
    from yoke_core.domain.agent_mission_restore import release_restored_case_host

    if release_restored_case_host(conn, execution, ordinal, lease.id):
        conn.commit()
        return None
    from yoke_core.domain.qa_plan_execution_abort_state import abort_request
    from yoke_core.domain.qa_plan_execution_schema import TERMINAL_PLAN_EXECUTION_STATES
    from yoke_core.domain.qa_deployment_execution_cleanup import abort_reason

    if execution["state"] not in TERMINAL_PLAN_EXECUTION_STATES:
        from yoke_core.domain.qa_plan_execution_lifecycle import (
            finish_plan_execution,
        )

        finish_plan_execution(
            conn,
            execution,
            state="aborted",
            commit=False,
            reason=abort_reason(
                conn,
                execution,
                MEMBER_REMOVED_REASON
                if member_removal_pending(execution)
                else (abort_request(execution) or {}).get(
                    "reason", "mission-teardown-finished"
                ),
            ),
        )
    conn.commit()
    return None


def handle_cleanup(request: Any, parsed: Any) -> HandlerOutcome | None:
    from yoke_core.domain.coordination_claims import CoordinationClaimError
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.machine_qa_outcomes import _failure
    from yoke_core.domain.machine_qa_capability import TestMachineCapabilityError
    from yoke_core.domain.machine_qa_execution_protocol import (
        MachineQaProtocolError,
        begin_host_control_execution,
        commit_deferred_connection,
    )
    from yoke_core.domain.machine_qa_plan_protocol import plan_case_contract_arguments
    from yoke_core.domain.qa_plan_execution_store import lock_plan_execution, marker
    from yoke_core.domain.qa_plan_lock import QaPlanBusy

    conn = connect()
    before = None
    try:
        execution = lock_plan_execution(conn, parsed.execution_id)
        before = dict(execution)
        if not cleanup_execution(conn, execution):
            if parsed.cleanup == "finish":
                raise ValueError(
                    "mission_cleanup_not_ended: cleanup custody requires an abort, member removal or a terminal run; inspect the execution with yoke qa plan get"
                )
            return None
        if not cleanup_authority(conn, request, execution):
            raise ValueError(
                "mission_cleanup_owner_required: only the execution's original "
                f"session {execution['session_id']} may run walk-end; ask that "
                "session to finish teardown"
            )
        ordinal, case, run_id = cleanup_mission(conn, execution, parsed.requirement_id)
        if parsed.run_id != run_id:
            raise ValueError(
                f"mission_cleanup_run_mismatch: rerun walk-end with --run-id {run_id}"
            )
        lease_id = case_host_lease_id(conn, execution, case)
        if parsed.cleanup == "finish":
            outcome = _finish(conn, request, parsed, execution, run_id)
            if outcome is not None:
                return outcome
            contract = None
        else:
            from yoke_core.domain.coordination_claims import get_claim
            from yoke_core.domain.machine_qa_plan_protocol import (
                continue_plan_host_control_execution,
            )

            arguments = plan_case_contract_arguments(execution, case, ordinal=ordinal)
            if lease_id is not None and get_claim(conn, lease_id).is_active:
                arguments.pop("operation")
                issued = continue_plan_host_control_execution(
                    conn,
                    project=case["project"],
                    session_id=request.actor.session_id,
                    actor_id=request.actor.actor_id,
                    lease_id=lease_id,
                    **arguments,
                )
            else:
                issued = begin_host_control_execution(
                    commit_deferred_connection(conn),
                    project=case["project"],
                    session_id=request.actor.session_id,
                    test_machine=original_host(conn, run_id),
                    select_any=False,
                    **arguments,
                )
                bind_case_host(conn, execution, case, issued.lease_id)
                p = marker(conn)
                conn.execute(
                    f"UPDATE qa_plan_executions SET test_machine_lease_id={p} WHERE id={p}",
                    (issued.lease_id, execution["id"]),
                )
            conn.commit()
            contract = issued.model_dump(mode="json")
        from yoke_core.domain.qa_plan_abort_reset import walk_reset_proven

        proven = contract is not None and walk_reset_proven(
            conn, execution, case, lease_id
        )
        return HandlerOutcome(
            primary_success=True,
            result_payload={
                "execution_id": str(execution["id"]),
                "requirement_id": parsed.requirement_id,
                "execution": contract,
                "cleanup_lease": True,
                "restore_proven": proven,
            },
        )
    except (
        CoordinationClaimError,
        MachineQaProtocolError,
        TestMachineCapabilityError,
        ValueError,
    ) as exc:
        conn.rollback()
        return _failure(
            "agent_mission_cleanup_failed",
            f"{exc}; {_unsettled(before)} Retry the same walk-end after "
            "resolving the named blocker",
        )
    except QaPlanBusy as exc:
        conn.rollback()  # Busy is a retryable lock answer, never a restore failure.
        raise QaPlanBusy(f"{exc} {_unsettled(before)}") from None
    finally:
        conn.close()
