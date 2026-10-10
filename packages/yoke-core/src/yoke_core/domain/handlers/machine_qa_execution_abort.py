"""Actor-bound release of interrupted host-control executions."""

from __future__ import annotations

from typing import Any, Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_core.domain.handlers.machine_qa import _failure
from yoke_core.domain.handlers.machine_qa_operation import (
    OperatorOperation,
    refuse_browser_profile_capture,
)
from yoke_core.domain.machine_qa_capability import TestMachineCapabilityError


AbortReason = Literal[
    "local_execution_failed",
    "submission_failed",
    "client_cancelled",
]


class TestMachineOperationAbortRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project: str
    lease_id: int = Field(ge=1)
    contract_digest: str = Field(min_length=1)
    operation: OperatorOperation
    # The issued shape, echoed back so the abort rebuilds the same contract it
    # is releasing.
    baseline: str | None = None
    destination: str | None = None
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


def _release(
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
    cases: Sequence[dict[str, Any]] = (),
    golden_destination: str | None = None,
) -> dict[str, Any]:
    from yoke_core.domain.machine_qa_execution_protocol import (
        validate_host_control_submission,
    )
    from yoke_core.domain.machine_qa_operation_lease import (
        operation_mission,
        finish_operation_execution,
    )

    mission = (
        operation_mission(conn, lease_id=lease_id, project=project, actor=request.actor)
        if operation != "case"
        else None
    )
    lease, _contract = validate_host_control_submission(
        conn,
        project=project,
        session_id=request.actor.session_id,
        actor_id=request.actor.actor_id,
        lease_id=lease_id,
        contract_digest=contract_digest,
        operation=operation,
        checks=checks,
        baselines=baselines,
        cases=cases,
        golden_destination=golden_destination,
    )
    released = finish_operation_execution(
        conn,
        lease,
        mission=mission,
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
        result = _release(
            conn,
            request=request,
            project=parsed.project,
            lease_id=parsed.lease_id,
            contract_digest=parsed.contract_digest,
            reason=parsed.reason,
            operation=parsed.operation,
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


def _case_target(
    request: FunctionCallRequest,
    function_id: str,
) -> int | HandlerOutcome:
    from yoke_core.domain.handlers.machine_qa_case import _target_requirement

    return _target_requirement(request, function_id)


def handle_case_abort(request: FunctionCallRequest) -> HandlerOutcome:
    target = _case_target(request, "test_machine.case.abort")
    if isinstance(target, HandlerOutcome):
        return target
    try:
        parsed = TestMachineCaseAbortRequest.model_validate(
            request.payload or {},
        )
    except ValidationError as exc:
        return _failure("payload_invalid", str(exc))
    from yoke_core.domain import db_helpers
    from yoke_core.domain.handlers.machine_qa_case import (
        _load_case,
        contract_baseline,
    )
    from yoke_core.domain.machine_qa_execution_protocol import (
        MachineQaProtocolError,
    )

    conn = db_helpers.connect()
    try:
        case = _load_case(conn, target)
        result = _release(
            conn,
            request=request,
            project=str(case["project"]),
            lease_id=parsed.lease_id,
            contract_digest=parsed.contract_digest,
            reason=parsed.reason,
            operation="case",
            baselines=tuple(contract_baseline(case)),
            cases=(case,),
        )
    except (MachineQaProtocolError, TestMachineCapabilityError, ValueError) as exc:
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
