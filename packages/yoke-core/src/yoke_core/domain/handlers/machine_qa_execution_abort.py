"""Actor-bound release of interrupted host-control executions."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_core.domain.handlers.machine_qa import _failure
from yoke_core.domain.machine_qa_capability import TestMachineCapabilityError


AbortReason = Literal[
    "local_execution_failed",
    "submission_failed",
    "client_cancelled",
]


class TestMachineVerifyAbortRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project: str
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


def _release(
    conn: Any,
    *,
    request: FunctionCallRequest,
    project: str,
    lease_id: int,
    contract_digest: str,
    reason: AbortReason,
    operation: Literal["verify", "case", "baseline_group"],
    checks: tuple[str, ...] = (),
    baselines: tuple[str, ...] = (),
    cases: tuple[dict[str, Any], ...] = (),
) -> dict[str, Any]:
    from yoke_core.domain.machine_qa_execution_protocol import (
        complete_host_control_execution,
        validate_host_control_submission,
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
    )
    complete_host_control_execution(
        conn,
        lease,
        reason=f"host-control-{reason.replace('_', '-')}",
    )
    return {
        "lease_id": lease.id,
        "released": True,
        "reason": reason,
    }


def handle_verify_abort(request: FunctionCallRequest) -> HandlerOutcome:
    try:
        parsed = TestMachineVerifyAbortRequest.model_validate(
            request.payload or {},
        )
    except ValidationError as exc:
        return _failure("payload_invalid", str(exc))
    from yoke_core.domain import db_helpers
    from yoke_core.domain.machine_qa_execution_protocol import (
        MachineQaProtocolError,
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
            operation="verify",
            checks=("connection", "terminal_bridge"),
            baselines=("fresh-host", "shell-preconfigured"),
        )
    except (MachineQaProtocolError, TestMachineCapabilityError, ValueError) as exc:
        conn.rollback()
        return _failure("test_machine_verification_abort_failed", str(exc))
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


def handle_baseline_group_abort(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    target = _case_target(request, "test_machine.baseline_group.abort")
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
        _baseline_group_cases,
        _load_case,
    )
    from yoke_core.domain.machine_qa_execution_protocol import (
        MachineQaProtocolError,
    )

    conn = db_helpers.connect()
    try:
        anchor = _load_case(conn, target)
        cases = _baseline_group_cases(conn, anchor=anchor)
        result = _release(
            conn,
            request=request,
            project=str(anchor["project"]),
            lease_id=parsed.lease_id,
            contract_digest=parsed.contract_digest,
            reason=parsed.reason,
            operation="baseline_group",
            baselines=(str(anchor["host_baseline"]),),
            cases=tuple(cases),
        )
    except (MachineQaProtocolError, TestMachineCapabilityError, ValueError) as exc:
        conn.rollback()
        return _failure("test_machine_baseline_group_abort_failed", str(exc))
    finally:
        conn.close()
    return HandlerOutcome(primary_success=True, result_payload=result)


__all__ = [
    "TestMachineCaseAbortRequest",
    "TestMachineExecutionAbortResponse",
    "TestMachineVerifyAbortRequest",
    "handle_baseline_group_abort",
    "handle_case_abort",
    "handle_verify_abort",
]
