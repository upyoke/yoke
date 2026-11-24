"""Actor-bound release of interrupted host-control executions."""

from __future__ import annotations

from typing import Any, Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_core.domain.handlers.machine_qa import _failure
from yoke_core.domain.handlers.machine_qa_operation import (
    TestMachineOperationShape,
    refuse_browser_profile_capture,
)
from yoke_core.domain.machine_qa_capability import TestMachineCapabilityError


AbortReason = Literal[
    "local_execution_failed",
    "submission_failed",
    "client_cancelled",
]


class TestMachineOperationAbortRequest(TestMachineOperationShape):
    lease_id: int = Field(ge=1)
    contract_digest: str = Field(min_length=1)
    reason: AbortReason


class TestMachineCaseAbortRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lease_id: int = Field(ge=1)
    contract_digest: str = Field(min_length=1)
    reason: AbortReason


class TestMachineExecutionAbortResponse(BaseModel):
    lease_id: int
    released: bool
    reason: AbortReason


def _release_operation(
    conn: Any,
    *,
    request: FunctionCallRequest,
    project: str,
    lease_id: int,
    contract_digest: str,
    reason: AbortReason,
    operation: str,
    checks: Sequence[str] = (),
    baselines: Sequence[str] = (),
    golden_destination: str | None = None,
    plan_execution_id: str | None = None,
) -> dict[str, Any]:
    from yoke_core.domain.qa_plan_abort_reset import (
        validate_operation_submission,
    )
    from yoke_core.domain.machine_qa_operation_lease import (
        operation_mission,
        finish_operation_execution,
        holds_plan_turn,
    )

    mission = operation_mission(
        conn,
        lease_id=lease_id,
        project=project,
        actor=request.actor,
        operation=operation,
        baselines=baselines,
        plan_execution_id=plan_execution_id,
    )
    from yoke_core.domain.qa_host_queue import lock_host_queue

    lock_host_queue(conn)
    lease, contract = validate_operation_submission(
        conn,
        project=project,
        mission=mission,
        actor=request.actor,
        lease_id=lease_id,
        contract_digest=contract_digest,
        operation=operation,
        checks=checks,
        baselines=baselines,
        golden_destination=golden_destination,
    )
    # Borrowed operations leave their host lease in the plan's custody.
    if (
        operation == "reset"
        and reason != "client_cancelled"
        and mission is None
        and not holds_plan_turn(conn, lease, request.actor)
    ):
        from yoke_core.domain.machine_operation_recording import (
            record_test_machine_operation,
        )

        record_test_machine_operation(
            conn,
            test_machine=contract.settings["resource_name"],
            operation=operation,
            status="error",
            checks=[{"name": contract.baselines[0], "ok": False}],
            error_code="machine_needs_repair",
            lease_id=lease.id,
            contract_digest=contract_digest,
            commit=False,
        )
    released = finish_operation_execution(
        conn,
        lease,
        mission=mission,
        contract_digest=contract_digest,
        reason=f"host-control-{reason.replace('_', '-')}",
    )
    return {
        "lease_id": lease.id,
        "released": released,
        "reason": reason,
    }


def handle_operation_abort(request: FunctionCallRequest) -> HandlerOutcome:
    """Release the lease of an operation whose local execution never finished."""
    payload = refuse_browser_profile_capture(request.payload)
    if isinstance(payload, HandlerOutcome):
        return payload
    try:
        parsed = TestMachineOperationAbortRequest.model_validate(payload or {})
    except ValidationError as exc:
        return _failure("payload_invalid", str(exc))
    from yoke_core.domain import db_helpers
    from yoke_core.domain.machine_qa_execution_protocol import (
        MachineQaProtocolError,
    )
    from yoke_core.domain.machine_qa_operation_shape import (
        TestMachineOperationShapeError,
        operation_contract_shape,
    )

    conn = db_helpers.connect()
    try:
        result = _release_operation(
            conn,
            request=request,
            project=parsed.project,
            lease_id=parsed.lease_id,
            contract_digest=parsed.contract_digest,
            reason=parsed.reason,
            operation=parsed.operation,
            plan_execution_id=parsed.plan_execution_id,
            **operation_contract_shape(
                parsed.operation,
                baseline=parsed.baseline,
                golden_destination=parsed.destination,
            ),
        )
    except (
        MachineQaProtocolError,
        TestMachineCapabilityError,
        TestMachineOperationShapeError,
        ValueError,
    ) as exc:
        conn.rollback()
        return _failure("test_machine_operation_abort_failed", str(exc))
    finally:
        conn.close()
    return HandlerOutcome(primary_success=True, result_payload=result)


def handle_case_abort(request: FunctionCallRequest) -> HandlerOutcome:
    from yoke_core.domain.handlers.machine_qa_case import _target_requirement

    target = _target_requirement(request, "test_machine.case.abort")
    if isinstance(target, HandlerOutcome):
        return target
    try:
        parsed = TestMachineCaseAbortRequest.model_validate(
            request.payload or {},
        )
    except ValidationError as exc:
        return _failure("payload_invalid", str(exc))
    from yoke_core.domain import db_helpers
    from yoke_core.domain.coordination_claims import CoordinationClaimNotFoundError
    from yoke_core.domain.host_lease_walk_heartbeat import lease_execution_id
    from yoke_core.domain.machine_qa_execution_protocol import complete_host_control_execution
    from yoke_core.domain.machine_qa_lease_messages import conflicting_lease, invalid_lease
    from yoke_core.domain.machine_qa_submission_lease import _lock_submission_claim
    from yoke_core.domain.qa_host_turns import HOST_TURN_REASON

    conn = db_helpers.connect()
    try:
        lease = _lock_submission_claim(conn, parsed.lease_id)
        machine = lease.target.test_machine
        if not machine:
            raise ValueError(invalid_lease(lease.id, "it does not name a machine"))
        actor_id = str(lease.actor_id) if lease.actor_id is not None else None
        if lease.session_id != request.actor.session_id or actor_id != request.actor.actor_id:
            raise ValueError(conflicting_lease(lease, machine, "a different session or actor owns it"))
        if not lease.is_active:
            raise ValueError(conflicting_lease(lease, machine, "the lease is no longer active"))
        if (lease.reason or "").startswith(HOST_TURN_REASON) or lease_execution_id(conn, lease):
            raise ValueError(
                f"qa_case_abort_plan_lease: lease {lease.id} is held for a QA plan. "
                "Use the plan's own abort command to finish the plan and release its host"
            )
        complete_host_control_execution(
            conn, lease, reason=f"host-control-{parsed.reason.replace('_', '-')}",
        )
        result = {"lease_id": lease.id, "released": True, "reason": parsed.reason}
    except CoordinationClaimNotFoundError:
        conn.rollback()
        return _failure(
            "test_machine_case_abort_failed",
            invalid_lease(parsed.lease_id, "no lease was issued with that id"),
        )
    except ValueError as exc:
        conn.rollback()
        return _failure("test_machine_case_abort_failed", str(exc))
    finally:
        conn.close()
    return HandlerOutcome(primary_success=True, result_payload=result)


__all__ = [
    "TestMachineCaseAbortRequest",
    "TestMachineExecutionAbortResponse",
    "TestMachineOperationAbortRequest",
    "handle_case_abort",
    "handle_operation_abort",
]
