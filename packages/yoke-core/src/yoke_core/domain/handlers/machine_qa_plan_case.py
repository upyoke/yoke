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
    require_plan_execution_owner(
        execution,
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
    return execution, case


def _assert_current_snapshot(conn: Any, case: dict[str, Any]) -> None:
    from yoke_core.domain.db_helpers import query_one
    from yoke_core.domain.qa_case_execution_context import (
        get_case_execution_context,
    )
    from yoke_core.domain.qa_plan_execution_store import canonical, marker

    requirement_id = int(case["requirement_id"])
    current = get_case_execution_context(conn, requirement_id=requirement_id)
    row = query_one(
        conn,
        "SELECT case_position,baseline_position FROM qa_requirements "
        f"WHERE id={marker(conn)}",
        (requirement_id,),
    )
    if row is None:
        raise ValueError("ordered plan requirement no longer exists")
    current["case_position"] = int(row["case_position"])
    current["baseline_position"] = int(row["baseline_position"])
    stored = {key: value for key, value in case.items() if key != "ordinal"}
    if canonical(current) != canonical(stored):
        raise ValueError("ordered plan case snapshot changed during execution")


def _contract_args(
    execution: dict[str, Any],
    case: dict[str, Any],
    *,
    ordinal: int,
) -> dict[str, Any]:
    from yoke_core.domain.qa_plan_execution_continuation import contract_baselines

    contract_case = {key: value for key, value in case.items() if key != "ordinal"}
    return {
        "operation": "plan_case",
        "baselines": contract_baselines(execution, case),
        "cases": (contract_case,),
        "plan_execution_id": str(execution["id"]),
        "roster_digest": str(execution["roster_digest"]),
        "ordinal": ordinal,
        "case_position": int(case["case_position"]),
        "baseline_position": int(case["baseline_position"]),
    }


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
        begin_host_control_execution,
        commit_deferred_connection,
    )
    from yoke_core.domain.machine_qa_plan_protocol import (
        continue_plan_host_control_execution,
    )
    from yoke_core.domain.qa_plan_execution_state import (
        finish_plan_execution,
        set_plan_machine_lease,
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
        arguments = _contract_args(execution, case, ordinal=parsed.ordinal)
        from yoke_core.domain.machine_qa_case_machine import resolve_case_machine

        machine = resolve_case_machine(case, parsed.machine)
        lease_id = execution.get("machine_lease_id")
        selection_new = lease_id is None
        try:
            if lease_id is None:
                contract = begin_host_control_execution(
                    commit_deferred_connection(conn),
                    project=str(case["project"]),
                    session_id=request.actor.session_id,
                    machine=machine,
                    **arguments,
                )
                set_plan_machine_lease(
                    conn,
                    execution,
                    lease_id=contract.lease_id,
                )
            else:
                contract = continue_plan_host_control_execution(
                    conn,
                    project=str(case["project"]),
                    session_id=request.actor.session_id,
                    actor_id=request.actor.actor_id,
                    lease_id=int(lease_id),
                    baselines=arguments["baselines"],
                    cases=arguments["cases"],
                    plan_execution_id=arguments["plan_execution_id"],
                    roster_digest=arguments["roster_digest"],
                    ordinal=arguments["ordinal"],
                    case_position=arguments["case_position"],
                    baseline_position=arguments["baseline_position"],
                    machine=machine,
                )
        except MachineQaProtocolLeaseHeld as held:
            finish_plan_execution(
                conn,
                execution,
                state="waiting",
                reason="test-machine-lease-waiting",
            )
            return HandlerOutcome(
                primary_success=True,
                result_payload={
                    "state": "waiting",
                    "execution_id": str(execution["id"]),
                    "cursor_ordinal": int(execution["cursor_ordinal"]),
                    "lease_context": waiting_claim_evidence(
                        held.lease,
                        held.contention,
                    ),
                },
            )
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
        "plan_id": int(case["plan_id"]),
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
        commit_deferred_connection,
        validate_host_control_submission,
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
        arguments = _contract_args(execution, case, ordinal=parsed.ordinal)
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
