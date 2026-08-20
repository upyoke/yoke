"""Two-phase authority and evidence recording for Machine QA cases."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_core.domain.handlers.machine_qa import _failure
from yoke_core.domain.handlers.machine_qa_case_evidence import (
    record_machine_case_result as _record_machine_case_result,
)
from yoke_core.domain.machine_qa_execution import MachineCaseResult
from yoke_core.domain.coordination_lease_contention import waiting_lease_evidence
from yoke_core.domain.machine_qa_execution_contract import (
    HostControlExecutionContract,
)
from yoke_core.domain.machine_qa_submission_recording import (
    MachineQaArtifactRollback,
    MachineCaseSubmissionResult,
    record_submitted_case,
    recorded_case_submission,
    rollback_machine_submission,
    validate_case_submission,
)
from yoke_core.domain.machine_qa_capability import TestMachineCapabilityError
from yoke_core.domain.qa_case_execution_context import (
    execution_host_capability_kinds,
)


class TestMachineCaseExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TestMachineCaseExecuteResponse(BaseModel):
    requirement_id: int
    runner_id: str
    verdict: str | None
    case_outcome: str
    run_id: int
    evidence_count: int
    capture_degraded_reason: str | None
    error_code: str | None
    lease_context: dict[str, Any] | None = None


class TestMachineCaseBeginResponse(BaseModel):
    state: Literal["ready", "waiting"]
    execution: HostControlExecutionContract | None = None
    result: TestMachineCaseExecuteResponse | None = None


class TestMachineCaseSubmitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lease_id: int = Field(ge=1)
    contract_digest: str = Field(min_length=1)
    results: list[MachineCaseSubmissionResult]


def _is_machine_case(case: dict[str, Any]) -> bool:
    from yoke_core.domain.machine_qa_method_contracts import MACHINE_METHODS

    return case["runner_id"] == "host_control" and case["method_id"] in MACHINE_METHODS


def _target_requirement(
    request: FunctionCallRequest,
    function_id: str,
) -> int | HandlerOutcome:
    requirement_id = request.target.qa_requirement_id
    if request.target.kind != "qa_requirement" or requirement_id is None:
        return _failure(
            "target_invalid",
            f"{function_id} requires target.kind='qa_requirement'",
        )
    return int(requirement_id)


def _waiting_result(held: Any) -> MachineCaseResult:
    return MachineCaseResult(
        case_outcome="waiting",
        verdict="waiting",
        evidence={
            "runner_id": "host_control",
            "machine": held.machine,
            "case_started": False,
            "lease": waiting_lease_evidence(held.lease, held.contention),
        },
    )


def handle_case_execute(request: FunctionCallRequest) -> HandlerOutcome:
    """Refuse direct server-side host control in favor of the CLI protocol."""
    target = _target_requirement(request, "test_machine.case_execute")
    if isinstance(target, HandlerOutcome):
        return target
    return _failure(
        "host_control_client_required",
        "Machine QA cannot execute on the hosted control plane; run "
        f"`yoke qa case run --requirement-id {target}` from a "
        "credential-owning harness or CLI machine",
    )


def _load_case(
    conn: Any,
    requirement_id: int,
    *,
    host_capability_kinds: Any | None = None,
) -> dict[str, Any]:
    from yoke_core.domain.qa_case_execution_context import (
        get_case_execution_context,
    )

    case = get_case_execution_context(
        conn,
        requirement_id=requirement_id,
        host_capability_kinds=host_capability_kinds,
    )
    if not _is_machine_case(case):
        raise ValueError("the requirement is not a registered Machine QA case")
    return case


def handle_case_begin(request: FunctionCallRequest) -> HandlerOutcome:
    target = _target_requirement(request, "test_machine.case.begin")
    if isinstance(target, HandlerOutcome):
        return target
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.machine_qa_execution_protocol import (
        MachineQaProtocolError,
        MachineQaProtocolLeaseHeld,
        begin_host_control_execution,
    )

    conn = connect()
    try:
        case = _load_case(
            conn,
            target,
            host_capability_kinds=execution_host_capability_kinds(
                conn,
                session_id=request.actor.session_id,
            ),
        )
        try:
            contract = begin_host_control_execution(
                conn,
                project=str(case["project"]),
                session_id=request.actor.session_id,
                actor_id=request.actor.actor_id,
                operation="case",
                baselines=(
                    (str(case["host_baseline"]),) if case.get("host_baseline") else ()
                ),
                cases=(case,),
            )
        except MachineQaProtocolLeaseHeld as held:
            result = _record_machine_case_result(
                conn,
                case=case,
                result=_waiting_result(held),
                duration_ms=0,
            )
            return HandlerOutcome(
                primary_success=True,
                result_payload={"state": "waiting", "result": result},
            )
    except (MachineQaProtocolError, TestMachineCapabilityError, ValueError) as exc:
        conn.rollback()
        return _failure("test_machine_case_begin_failed", str(exc))
    finally:
        conn.close()
    return HandlerOutcome(
        primary_success=True,
        result_payload={
            "state": "ready",
            "execution": contract.model_dump(mode="json"),
        },
    )


def handle_case_submit(request: FunctionCallRequest) -> HandlerOutcome:
    target = _target_requirement(request, "test_machine.case.submit")
    if isinstance(target, HandlerOutcome):
        return target
    try:
        parsed = TestMachineCaseSubmitRequest.model_validate(request.payload or {})
    except ValidationError as exc:
        return _failure("payload_invalid", str(exc))
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.machine_qa_execution_protocol import (
        MachineQaProtocolError,
        commit_deferred_connection,
        complete_host_control_execution,
        validate_host_control_submission,
    )

    conn = connect()
    artifact_rollback = MachineQaArtifactRollback()
    try:
        case = _load_case(conn, target)
        lease, contract = validate_host_control_submission(
            conn,
            project=str(case["project"]),
            session_id=request.actor.session_id,
            actor_id=request.actor.actor_id,
            lease_id=parsed.lease_id,
            contract_digest=parsed.contract_digest,
            operation="case",
            baselines=tuple(contract_baseline(case)),
            cases=(case,),
            allow_recorded_replay=True,
        )
        if len(parsed.results) != 1:
            raise ValueError("single-case submission requires exactly one result")
        submitted_result = parsed.results[0]
        validate_case_submission(
            case,
            submitted_result,
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
                raise ValueError(
                    "host-control lease is released without a recorded case result"
                )
            with TemporaryDirectory(prefix="yoke-machine-qa-") as temp_dir:
                result = record_submitted_case(
                    commit_deferred_connection(conn),
                    case=case,
                    result=submitted_result,
                    resource_name=contract.settings["resource_name"],
                    artifact_root=Path(temp_dir),
                    lease_id=lease.id,
                    contract_digest=parsed.contract_digest,
                    artifact_rollback=artifact_rollback,
                )
        if lease.is_active:
            complete_host_control_execution(
                conn,
                lease,
                reason="machine-qa-case-complete",
            )
        else:
            conn.commit()
        artifact_rollback.preserve()
    except (MachineQaProtocolError, TestMachineCapabilityError, ValueError) as exc:
        rollback_machine_submission(conn, artifact_rollback)
        return _failure("test_machine_case_submit_failed", str(exc))
    except Exception:
        rollback_machine_submission(conn, artifact_rollback)
        raise
    finally:
        conn.close()
    return HandlerOutcome(primary_success=True, result_payload=result)


def contract_baseline(case: dict[str, Any]) -> list[str]:
    baseline = str(case.get("host_baseline") or "")
    return [baseline] if baseline else []


from yoke_core.domain.handlers.machine_qa_baseline_group import (  # noqa: E402
    TestMachineBaselineGroupBeginResponse,
    TestMachineBaselineGroupExecuteRequest,
    TestMachineBaselineGroupExecuteResponse,
    TestMachineBaselineGroupSubmitRequest,
    _baseline_group_cases,
    handle_baseline_group_begin,
    handle_baseline_group_execute,
    handle_baseline_group_submit,
)


__all__ = [
    "TestMachineBaselineGroupBeginResponse",
    "TestMachineBaselineGroupExecuteRequest",
    "TestMachineBaselineGroupExecuteResponse",
    "TestMachineBaselineGroupSubmitRequest",
    "TestMachineCaseBeginResponse",
    "TestMachineCaseExecuteRequest",
    "TestMachineCaseExecuteResponse",
    "TestMachineCaseSubmitRequest",
    "_baseline_group_cases",
    "_record_machine_case_result",
    "handle_baseline_group_begin",
    "handle_baseline_group_execute",
    "handle_baseline_group_submit",
    "handle_case_begin",
    "handle_case_execute",
    "handle_case_submit",
]
