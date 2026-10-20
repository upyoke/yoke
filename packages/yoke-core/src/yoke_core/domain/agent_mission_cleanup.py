"""Owner-only host custody for teardown after deployment membership ends.

Removal leaves a walk holding its machine live under a recorded abort; its
walk-end teardown is the cleanup proof, so finishing it releases the host
and settles that abort in one transaction.
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
from yoke_core.domain.qa_plan_execution_store import same_owner


def removed_execution(execution: dict) -> bool:
    return member_removed(execution) or member_removal_pending(execution)


def cleanup_request(request: Any) -> bool:
    return request.function == "test_machine.mission.access" and (
        request.payload or {}
    ).get("cleanup") in ("begin", "finish")


def cleanup_authority(request: Any, execution: dict) -> bool:
    """The removed execution grants only its original session teardown."""
    from yoke_core.domain.qa_plan_execution_authority import (
        require_plan_execution_subject,
    )

    if not cleanup_request(request) or not removed_execution(execution):
        return False
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
        return cleanup_authority(request, execution)
    except (LookupError, ValueError):
        return False
    finally:
        conn.close()


def _mission(conn: Any, execution: dict, requirement_id: int) -> tuple[int, dict, int]:
    from yoke_core.domain.qa_plan_execution_store import result_rows

    matches = [
        (ordinal, case)
        for ordinal, case in enumerate(execution["roster"])
        if int(case["requirement_id"]) == requirement_id
        and case.get("runner_id") == "agent_mission"
    ]
    results = [
        r
        for r in result_rows(conn, str(execution["id"]))
        if r["requirement_id"] == requirement_id
    ]
    if len(matches) != 1 or len(results) != 1:
        raise ValueError(
            "mission_cleanup_docket_missing: no recorded mission matches this "
            "execution; ask the control-plane operator to inspect its docket"
        )
    ordinal, case = matches[0]
    return ordinal, case, int(results[0]["result"]["run_id"])


def _original_host(conn: Any, run_id: int) -> str:
    from yoke_core.domain.coordination_claims import get_claim
    from yoke_core.domain.db_helpers import query_one

    row = query_one(conn, "SELECT raw_result FROM qa_runs WHERE id=%s", (run_id,))
    raw = json.loads(row["raw_result"]) if row else {}
    lease_id = raw.get("host_control_submission", {}).get("lease_id")
    if not lease_id:
        raise ValueError(
            "mission_cleanup_host_unknown: the docket has no original lease; "
            "ask the control-plane operator to recover the host identity"
        )
    machine = get_claim(conn, int(lease_id)).target.machine_id
    if not machine:
        raise ValueError("mission_cleanup_host_unknown: inspect the docket's lease")
    return str(machine)


def _finish(
    conn: Any, request: Any, parsed: Any, execution: dict, run_id: int
) -> HandlerOutcome | None:
    from yoke_core.domain.coordination_claims import get_claim, release
    from yoke_core.domain.qa_plan_execution_store import marker

    lease_id = execution.get("machine_lease_id")
    if lease_id is None or parsed.lease_id != lease_id:
        raise ValueError(
            "mission_cleanup_lease_mismatch: rerun walk-end to acquire cleanup custody"
        )
    lease = get_claim(conn, lease_id)
    if lease.session_id != request.actor.session_id:
        raise ValueError(
            "mission_cleanup_owner_required: cleanup lease belongs to another session"
        )
    outcome = None
    try:
        if parsed.restore is not None:
            from yoke_core.domain.handlers.qa_artifact_add import handle_qa_artifact_add
            from yoke_core.domain.machine_qa_submission_artifacts import (
                ensure_secret_free_result,
            )

            ensure_secret_free_result(parsed.restore)
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
            outcome = handle_qa_artifact_add(artifact_request)
    except Exception:
        from yoke_core.domain.handlers.machine_qa import _failure

        outcome = _failure(
            "mission_restore_evidence_failed",
            "Restore evidence could not be stored; inspect artifact storage and "
            "run yoke test-machine reset before using this machine again",
        )
    from yoke_core.domain.machine_reset_debt import record_reset_owed
    from yoke_core.domain.qa_plan_execution_abort_state import restore_cleanup_proven

    _, case, _ = _mission(conn, execution, parsed.requirement_id)
    if not restore_cleanup_proven(parsed.restore or {}, case.get("host_baseline")) or (
        outcome is not None and not outcome.primary_success
    ):
        record_reset_owed(
            conn, case=case, machine=lease.target.machine_id, lease_id=lease.id
        )
    release(conn, lease.id, "mission-teardown-finished", commit=False)
    conn.execute(
        f"UPDATE qa_plan_executions SET machine_lease_id=NULL WHERE id={marker(conn)}",
        (execution["id"],),
    )
    execution["machine_lease_id"] = None
    if member_removal_pending(execution):
        from yoke_core.domain.qa_plan_execution_lifecycle import (
            finish_plan_execution,
        )

        finish_plan_execution(
            conn, execution, state="aborted", reason=MEMBER_REMOVED_REASON, commit=False
        )
    conn.commit()
    return outcome if outcome is not None and not outcome.primary_success else None


def handle_cleanup(request: Any, parsed: Any) -> HandlerOutcome | None:
    from yoke_core.domain.coordination_claims import CoordinationClaimError
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.handlers.machine_qa import _failure
    from yoke_core.domain.machine_qa_capability import TestMachineCapabilityError
    from yoke_core.domain.machine_qa_execution_protocol import (
        MachineQaProtocolError,
        begin_host_control_execution,
        commit_deferred_connection,
    )
    from yoke_core.domain.machine_qa_plan_protocol import plan_case_contract_arguments
    from yoke_core.domain.qa_plan_execution_store import lock_plan_execution, marker

    conn = connect()
    try:
        execution = lock_plan_execution(conn, parsed.execution_id)
        if not removed_execution(execution):
            if parsed.cleanup == "finish":
                raise ValueError(
                    "mission_cleanup_not_removed: only removed missions release a cleanup lease"
                )
            return None
        if not cleanup_authority(request, execution):
            raise ValueError(
                "mission_cleanup_owner_required: only the execution's original "
                f"session {execution['session_id']} may run walk-end; ask that "
                "session to finish teardown"
            )
        ordinal, case, run_id = _mission(conn, execution, parsed.requirement_id)
        if parsed.run_id != run_id:
            raise ValueError(
                f"mission_cleanup_run_mismatch: rerun walk-end with --run-id {run_id}"
            )
        lease_id = execution.get("machine_lease_id")
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
                    machine=_original_host(conn, run_id),
                    select_any=False,
                    **arguments,
                )
                p = marker(conn)
                conn.execute(
                    f"UPDATE qa_plan_executions SET machine_lease_id={p} WHERE id={p}",
                    (issued.lease_id, execution["id"]),
                )
            conn.commit()
            contract = issued.model_dump(mode="json")
        return HandlerOutcome(
            primary_success=True,
            result_payload={
                "execution_id": str(execution["id"]),
                "requirement_id": parsed.requirement_id,
                "execution": contract,
                "cleanup_lease": True,
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
            f"{exc}; retry the same walk-end after resolving the named blocker",
        )
    finally:
        conn.close()
