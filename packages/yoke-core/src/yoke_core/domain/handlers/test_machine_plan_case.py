"""Plan-scoped Machine QA under one uninterrupted server-owned lease."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from pydantic import BaseModel, ValidationError

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_core.domain.handlers.test_machine import _failure
from yoke_core.domain.handlers.test_machine_plan_case_models import (
    TestMachinePlanCaseBeginRequest,
    TestMachinePlanCaseBeginResponse,
    TestMachinePlanCaseSubmitRequest,
    TestMachinePlanCaseSubmitResponse,
)
from yoke_core.domain.machine_qa_submission_recording import (
    MachineQaArtifactRollback,
    record_submitted_case,
    recorded_case_submission,
    rollback_machine_submission,
    validate_case_submission,
)
from yoke_core.domain.test_machine_capability import TestMachineCapabilityError


def _target_item(
    request: FunctionCallRequest,
    function_id: str,
) -> int | HandlerOutcome:
    if request.target.kind != "item" or request.target.item_id is None:
        return _failure(
            "target_invalid",
            f"{function_id} requires target.kind='item'",
        )
    return int(request.target.item_id)


def _parse(model: type[BaseModel], payload: Any) -> BaseModel | HandlerOutcome:
    try:
        return model.model_validate(payload or {})
    except ValidationError as exc:
        return _failure("payload_invalid", str(exc))


def _owned_case(
    conn: Any,
    request: FunctionCallRequest,
    parsed: TestMachinePlanCaseBeginRequest,
    item_id: int,
    *,
    replay: bool,
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
        actor_id=request.actor.actor_id,
        session_id=request.actor.session_id,
    )
    case = expected_plan_case(
        execution,
        ordinal=parsed.ordinal,
        requirement_id=parsed.requirement_id,
        allow_replay=replay,
    )
    if case.get("executor_id") != "host_control":
        raise ValueError("the ordered plan case is not a host-control case")
    _assert_current_snapshot(conn, case)
    return execution, case


def _assert_current_snapshot(conn: Any, case: dict[str, Any]) -> None:
    from yoke_core.domain.db_helpers import query_one
    from yoke_core.domain.qa_case_execution_context import (
        get_case_execution_context,
    )
    from yoke_core.domain.qa_plan_execution_store import canonical, marker

    current = get_case_execution_context(
        conn,
        requirement_id=int(case["requirement_id"]),
    )
    row = query_one(
        conn,
        "SELECT case_position,baseline_position FROM qa_requirements "
        f"WHERE id={marker(conn)}",
        (int(case["requirement_id"]),),
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
    baseline = str(case.get("host_baseline") or "")
    contract_case = {key: value for key, value in case.items() if key != "ordinal"}
    return {
        "operation": "plan_case",
        "baselines": (baseline,) if baseline else (),
        "cases": (contract_case,),
        "plan_execution_id": str(execution["id"]),
        "roster_digest": str(execution["roster_digest"]),
        "ordinal": ordinal,
        "case_position": int(case["case_position"]),
        "baseline_position": int(case["baseline_position"]),
    }


def handle_plan_case_begin(request: FunctionCallRequest) -> HandlerOutcome:
    target = _target_item(request, "test_machine.plan_case.begin")
    if isinstance(target, HandlerOutcome):
        return target
    parsed = _parse(TestMachinePlanCaseBeginRequest, request.payload)
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
        execution, case = _owned_case(conn, request, parsed, target, replay=False)
        arguments = _contract_args(execution, case, ordinal=parsed.ordinal)
        lease_id = execution.get("machine_lease_id")
        try:
            if lease_id is None:
                contract = begin_host_control_execution(
                    commit_deferred_connection(conn),
                    project=str(case["project"]),
                    session_id=request.actor.session_id,
                    actor_id=request.actor.actor_id,
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
                )
        except MachineQaProtocolLeaseHeld:
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
    target = _target_item(request, "test_machine.plan_case.submit")
    if isinstance(target, HandlerOutcome):
        return target
    parsed = _parse(TestMachinePlanCaseSubmitRequest, request.payload)
    if isinstance(parsed, HandlerOutcome):
        return parsed
    assert isinstance(parsed, TestMachinePlanCaseSubmitRequest)

    from yoke_core.domain.coordination_leases import heartbeat_lease
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
        execution, case = _owned_case(conn, request, parsed, target, replay=True)
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
            heartbeat_lease(commit_deferred_connection(conn), lease.id)
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
