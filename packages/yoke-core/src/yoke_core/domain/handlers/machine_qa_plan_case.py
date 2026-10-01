"""Plan-scoped Machine QA under one uninterrupted server-owned lease."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_core.domain.handlers.machine_qa import _failure
from yoke_core.domain.handlers.machine_qa_plan_case_models import (
    TestMachinePlanCaseBeginRequest,
    TestMachinePlanCaseBeginResponse,
    TestMachinePlanCaseSubmitRequest,
    TestMachinePlanCaseSubmitResponse,
)
from yoke_core.domain.handlers.machine_qa_plan_case_request import (
    parse_plan_case_request,
    target_plan_subject,
)
from yoke_core.domain.machine_qa_submission_recording import (
    MachineQaArtifactRollback,
    record_submitted_case,
    recorded_case_submission,
    rollback_machine_submission,
    validate_case_submission,
)
from yoke_core.domain.machine_qa_capability import TestMachineCapabilityError
from yoke_core.domain.coordination_claim_contention import waiting_claim_evidence


def _owned_case(
    conn: Any,
    request: FunctionCallRequest,
    parsed: TestMachinePlanCaseBeginRequest,
    item_id: int | None,
    deployment_run_id: str | None,
    *,
    replay: bool,
    expected_runner: str | None = "host_control",
) -> tuple[dict[str, Any], dict[str, Any]]:
    from yoke_core.domain.qa_plan_execution_state import (
        expected_plan_case,
        lock_plan_execution,
        require_plan_execution_owner,
    )

    execution = lock_plan_execution(conn, parsed.execution_id)
    if request.target.kind == "global":
        from yoke_core.domain.qa_standalone_execution import require_standalone_project

        require_standalone_project(conn, execution, str(request.target.project_id))
    require_plan_execution_owner(
        execution,
        conn=conn,
        item_id=item_id,
        deployment_run_id=deployment_run_id,
        actor_id=request.actor.actor_id,
        session_id=request.actor.session_id,
    )
    case = expected_plan_case(
        execution,
        ordinal=parsed.ordinal,
        requirement_id=parsed.requirement_id,
        allow_replay=replay,
    )
    if expected_runner is not None and case.get("runner_id") != expected_runner:
        raise ValueError(f"the ordered plan case is not a {expected_runner} case")
    _assert_current_snapshot(conn, case)
    if replay and parsed.ordinal >= int(execution["cursor_ordinal"]):
        from yoke_core.domain.qa_plan_host_leases import require_case_host_leases

        require_case_host_leases(conn, execution, case)
    return execution, case


def _assert_current_snapshot(conn: Any, case: dict[str, Any]) -> None:
    from yoke_core.domain.db_helpers import query_one
    from yoke_core.domain.machine_qa_plan_case_snapshot import case_positions
    from yoke_core.domain.qa_case_execution_context import (
        get_case_execution_context,
    )
    from yoke_core.domain.qa_plan_case_currency import require_current_requirement
    from yoke_core.domain.qa_plan_execution_store import canonical, marker

    requirement_id = int(case["requirement_id"])
    # An amendment that landed after the roster froze is named here rather
    # than surfacing as an anonymous snapshot change.
    require_current_requirement(conn, requirement_id)
    current = get_case_execution_context(conn, requirement_id=requirement_id)
    row = query_one(
        conn,
        "SELECT case_position,baseline_position FROM qa_requirements "
        f"WHERE id={marker(conn)}",
        (requirement_id,),
    )
    if row is None:
        raise ValueError("ordered plan requirement no longer exists")
    current["case_position"], current["baseline_position"] = case_positions(case, row)
    stored = {key: value for key, value in case.items() if key != "ordinal"}
    if canonical(current) != canonical(stored):
        raise ValueError("ordered plan case snapshot changed during execution")


def handle_plan_case_begin(request: FunctionCallRequest) -> HandlerOutcome:
    target = target_plan_subject(request, "test_machine.plan_case.begin")
    if isinstance(target, HandlerOutcome):
        return target
    item_id, deployment_run_id = target
    parsed = parse_plan_case_request(TestMachinePlanCaseBeginRequest, request.payload)
    if isinstance(parsed, HandlerOutcome):
        return parsed
    assert isinstance(parsed, TestMachinePlanCaseBeginRequest)

    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.machine_qa_execution_protocol import (
        MachineQaProtocolError,
        MachineQaProtocolLeaseHeld,
    )

    conn = connect()
    try:
        execution, case = _owned_case(
            conn,
            request,
            parsed,
            item_id,
            deployment_run_id,
            replay=False,
            expected_runner=None,
        )
        if case.get("runner_id") not in {"host_control", "agent_mission"}:
            raise ValueError("the ordered plan case is not machine-backed")
        selection_new = execution.get("machine_lease_id") is None
        from yoke_core.domain.qa_plan_host_leases import begin_case_host_contract

        try:
            contract = begin_case_host_contract(
                conn,
                execution,
                case,
                ordinal=parsed.ordinal,
                machine=parsed.machine,
                actor_id=request.actor.actor_id,
                session_id=request.actor.session_id,
            )
        except MachineQaProtocolLeaseHeld as held:
            from yoke_core.domain.qa_host_turns import record_host_wait

            waiting = record_host_wait(
                conn,
                execution,
                machine=held.machine,
                rationale=f"lease {held.lease.id} held by {held.lease.session_id}",
            )
            waiting["lease_context"] = waiting_claim_evidence(
                held.lease, held.contention
            )
            return HandlerOutcome(primary_success=True, result_payload=waiting)
    except (MachineQaProtocolError, TestMachineCapabilityError, ValueError) as exc:
        conn.rollback()
        return _failure("test_machine_plan_case_begin_failed", str(exc))
    finally:
        conn.close()
    return HandlerOutcome(
        primary_success=True,
        result_payload={
            "state": "ready",
            "execution_id": str(execution["id"]),
            "cursor_ordinal": int(execution["cursor_ordinal"]),
            "execution": contract.model_dump(mode="json"),
            "selection_new": selection_new,
        },
    )


def _normalized_result(
    case: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    return {
        "plan_id": (int(case["plan_id"]) if case.get("plan_id") is not None else None),
        "case_key": str(case["case_key"]),
        "case_position": int(case["case_position"]),
        "baseline_position": int(case["baseline_position"]),
        "host_baseline": case.get("host_baseline"),
        **result,
    }


def handle_plan_case_submit(request: FunctionCallRequest) -> HandlerOutcome:
    target = target_plan_subject(request, "test_machine.plan_case.submit")
    if isinstance(target, HandlerOutcome):
        return target
    item_id, deployment_run_id = target
    parsed = parse_plan_case_request(TestMachinePlanCaseSubmitRequest, request.payload)
    if isinstance(parsed, HandlerOutcome):
        return parsed
    assert isinstance(parsed, TestMachinePlanCaseSubmitRequest)

    from yoke_core.domain.coordination_claims import heartbeat
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.machine_qa_execution_protocol import (
        MachineQaProtocolError,
        validate_host_control_submission,
        commit_deferred_connection,
    )
    from yoke_core.domain.qa_plan_execution_state import advance_plan_execution

    conn = connect()
    artifact_rollback = MachineQaArtifactRollback()
    try:
        execution, case = _owned_case(
            conn,
            request,
            parsed,
            item_id,
            deployment_run_id,
            replay=True,
        )
        from yoke_core.domain.machine_qa_plan_protocol import (
            plan_case_contract_arguments,
        )

        arguments = plan_case_contract_arguments(
            execution, case, ordinal=parsed.ordinal
        )
        lease, contract = validate_host_control_submission(
            conn,
            project=str(case["project"]),
            session_id=request.actor.session_id,
            actor_id=request.actor.actor_id,
            lease_id=parsed.lease_id,
            contract_digest=parsed.contract_digest,
            allow_recorded_replay=True,
            **arguments,
        )
        if (
            parsed.ordinal == int(execution["cursor_ordinal"])
            and execution.get("machine_lease_id") != lease.id
        ):
            raise ValueError("plan case submission names the wrong machine lease")
        if len(parsed.results) != 1:
            raise ValueError("plan case submission requires exactly one result")
        submitted = parsed.results[0]
        validate_case_submission(
            case,
            submitted,
            resource_name=contract.settings["resource_name"],
        )
        result = recorded_case_submission(
            conn,
            requirement_id=int(case["requirement_id"]),
            lease_id=lease.id,
            contract_digest=parsed.contract_digest,
        )
        if result is None:
            if not lease.is_active:
                raise ValueError("released plan lease has no recorded case result")
            with TemporaryDirectory(prefix="yoke-machine-qa-") as temp_dir:
                result = record_submitted_case(
                    commit_deferred_connection(conn),
                    case=case,
                    result=submitted,
                    resource_name=contract.settings["resource_name"],
                    artifact_root=Path(temp_dir),
                    lease_id=lease.id,
                    contract_digest=parsed.contract_digest,
                    artifact_rollback=artifact_rollback,
                )
        normalized = _normalized_result(case, result)
        advance_plan_execution(
            conn,
            execution,
            ordinal=parsed.ordinal,
            requirement_id=parsed.requirement_id,
            result=normalized,
            commit=False,
        )
        if lease.is_active:
            heartbeat(commit_deferred_connection(conn), lease.id)
        conn.commit()
        artifact_rollback.preserve()
    except (MachineQaProtocolError, TestMachineCapabilityError, ValueError) as exc:
        rollback_machine_submission(conn, artifact_rollback)
        return _failure("test_machine_plan_case_submit_failed", str(exc))
    except Exception:
        rollback_machine_submission(conn, artifact_rollback)
        raise
    finally:
        conn.close()
    return HandlerOutcome(
        primary_success=True,
        result_payload={
            "execution_id": str(execution["id"]),
            "cursor_ordinal": int(execution["cursor_ordinal"]),
            "result": normalized,
        },
    )


__all__ = [
    "TestMachinePlanCaseBeginRequest",
    "TestMachinePlanCaseBeginResponse",
    "TestMachinePlanCaseSubmitRequest",
    "TestMachinePlanCaseSubmitResponse",
    "handle_plan_case_begin",
    "handle_plan_case_submit",
]
