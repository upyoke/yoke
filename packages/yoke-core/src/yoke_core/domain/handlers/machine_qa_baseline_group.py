"""Two-phase authority for one Machine QA host-baseline group."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_core.domain.handlers.machine_qa import _failure
from yoke_core.domain.handlers.machine_qa_case import (
    TestMachineCaseExecuteResponse,
    TestMachineCaseSubmitRequest,
    _load_case,
    _record_machine_case_result,
    _target_requirement,
    _waiting_result,
)
from yoke_core.domain.handlers.machine_qa_baseline_group_context import (
    baseline_group_cases as _baseline_group_cases,
)
from yoke_core.domain.machine_qa_execution_contract import (
    HostControlExecutionContract,
)
from yoke_core.domain.machine_qa_submission_recording import (
    MachineQaArtifactRollback,
    record_submitted_case,
    recorded_case_submission,
    rollback_machine_submission,
    validate_case_submission,
)
from yoke_core.domain.machine_qa_capability import TestMachineCapabilityError
from yoke_core.domain.qa_case_execution_context import execution_host_capability_kinds


class TestMachineBaselineGroupExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TestMachineBaselineGroupExecuteResponse(BaseModel):
    anchor_requirement_id: int
    plan_id: int
    host_baseline: str
    baseline_ok: bool | None
    requirement_ids: list[int]
    results: list[TestMachineCaseExecuteResponse]


class TestMachineBaselineGroupBeginResponse(BaseModel):
    state: Literal["ready", "waiting"]
    execution: HostControlExecutionContract | None = None
    result: TestMachineBaselineGroupExecuteResponse | None = None


class TestMachineBaselineGroupSubmitRequest(TestMachineCaseSubmitRequest):
    baseline_ok: bool


def handle_baseline_group_execute(request: FunctionCallRequest) -> HandlerOutcome:
    target = _target_requirement(
        request,
        "test_machine.baseline_group_execute",
    )
    if isinstance(target, HandlerOutcome):
        return target
    return _failure(
        "host_control_client_required",
        "Machine QA cannot execute on the hosted control plane; run the "
        f"baseline group from a credential-owning harness using anchor {target}",
    )


def handle_baseline_group_begin(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    target = _target_requirement(
        request,
        "test_machine.baseline_group.begin",
    )
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
        host_capabilities = execution_host_capability_kinds(
            conn,
            session_id=request.actor.session_id,
        )
        anchor = _load_case(
            conn,
            target,
            host_capability_kinds=host_capabilities,
        )
        cases = _baseline_group_cases(
            conn,
            anchor=anchor,
            host_capability_kinds=host_capabilities,
        )
        try:
            contract = begin_host_control_execution(
                conn,
                project=str(anchor["project"]),
                session_id=request.actor.session_id,
                actor_id=request.actor.actor_id,
                operation="baseline_group",
                baselines=(str(anchor["host_baseline"]),),
                cases=cases,
            )
        except MachineQaProtocolLeaseHeld as held:
            results = [
                _record_machine_case_result(
                    conn,
                    case=case,
                    result=_waiting_result(held),
                    duration_ms=0,
                )
                for case in cases
            ]
            return HandlerOutcome(
                primary_success=True,
                result_payload={
                    "state": "waiting",
                    "result": _group_result(
                        anchor,
                        cases,
                        results,
                        None,
                    ),
                },
            )
    except (MachineQaProtocolError, TestMachineCapabilityError, ValueError) as exc:
        conn.rollback()
        return _failure("test_machine_baseline_group_begin_failed", str(exc))
    finally:
        conn.close()
    return HandlerOutcome(
        primary_success=True,
        result_payload={
            "state": "ready",
            "execution": contract.model_dump(mode="json"),
        },
    )


def _group_result(
    anchor: dict[str, Any],
    cases: list[dict[str, Any]],
    results: list[dict[str, Any]],
    baseline_ok: bool | None,
) -> dict[str, Any]:
    return {
        "anchor_requirement_id": int(anchor["requirement_id"]),
        "plan_id": int(anchor["plan_id"]),
        "host_baseline": str(anchor["host_baseline"]),
        "baseline_ok": baseline_ok,
        "requirement_ids": [int(case["requirement_id"]) for case in cases],
        "results": results,
    }


def _record_failed_baseline(
    conn: Any,
    *,
    contract: HostControlExecutionContract,
    lease_id: int,
    contract_digest: str,
    baseline: str,
    result: Any,
) -> None:
    from yoke_core.domain.machine_qa_execution_protocol import (
        commit_deferred_connection,
    )
    from yoke_core.domain.machine_verification_recording import (
        record_test_machine_verification,
        recorded_test_machine_verification,
    )

    recorded = recorded_test_machine_verification(
        conn,
        contract.project_id,
        lease_id=lease_id,
        contract_digest=contract_digest,
    )
    if recorded is not None:
        return
    evidence = result.evidence.get("baseline_evidence")
    check = dict(evidence) if isinstance(evidence, Mapping) else {}
    check.update({"name": baseline, "ok": False})
    record_test_machine_verification(
        commit_deferred_connection(conn),
        contract.project_id,
        status="error",
        checks=[check],
        error_code=str(result.error_code),
        lease_id=lease_id,
        contract_digest=contract_digest,
    )


def handle_baseline_group_submit(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    target = _target_requirement(
        request,
        "test_machine.baseline_group.submit",
    )
    if isinstance(target, HandlerOutcome):
        return target
    try:
        parsed = TestMachineBaselineGroupSubmitRequest.model_validate(
            request.payload or {},
        )
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
        anchor = _load_case(conn, target)
        cases = _baseline_group_cases(conn, anchor=anchor)
        lease, contract = validate_host_control_submission(
            conn,
            project=str(anchor["project"]),
            session_id=request.actor.session_id,
            actor_id=request.actor.actor_id,
            lease_id=parsed.lease_id,
            contract_digest=parsed.contract_digest,
            operation="baseline_group",
            baselines=(str(anchor["host_baseline"]),),
            cases=cases,
            allow_recorded_replay=True,
        )
        expected_ids = [int(case["requirement_id"]) for case in cases]
        if [row.requirement_id for row in parsed.results] != expected_ids:
            raise ValueError(
                "baseline-group submission does not match issued membership"
            )
        blocked = [
            row.case_outcome == "blocked_on_precondition" for row in parsed.results
        ]
        expected_blocked = [
            isinstance(case["method_config"].get("execution_blocker"), dict)
            for case in cases
        ]
        if (not parsed.baseline_ok and not all(blocked)) or (
            parsed.baseline_ok and blocked != expected_blocked
        ):
            raise ValueError("baseline-group result disagrees with baseline outcome")
        for case, row in zip(cases, parsed.results):
            validate_case_submission(
                case,
                row,
                resource_name=contract.settings["resource_name"],
            )
        results = [
            recorded_case_submission(
                conn,
                requirement_id=int(case["requirement_id"]),
                lease_id=lease.id,
                contract_digest=parsed.contract_digest,
            )
            for case in cases
        ]
        if not lease.is_active and any(result is None for result in results):
            raise ValueError(
                "host-control lease is released without a complete recorded "
                "baseline group"
            )
        with TemporaryDirectory(prefix="yoke-machine-qa-") as temp_dir:
            results = [
                recorded
                if recorded is not None
                else record_submitted_case(
                    commit_deferred_connection(conn),
                    case=case,
                    result=submitted,
                    resource_name=contract.settings["resource_name"],
                    artifact_root=Path(temp_dir) / str(submitted.requirement_id),
                    lease_id=lease.id,
                    contract_digest=parsed.contract_digest,
                    artifact_rollback=artifact_rollback,
                )
                for case, submitted, recorded in zip(
                    cases,
                    parsed.results,
                    results,
                )
            ]
        if not parsed.baseline_ok:
            _record_failed_baseline(
                conn,
                contract=contract,
                lease_id=lease.id,
                contract_digest=parsed.contract_digest,
                baseline=str(anchor["host_baseline"]),
                result=parsed.results[0],
            )
        if lease.is_active:
            complete_host_control_execution(
                conn,
                lease,
                reason="machine-qa-baseline-group-complete",
            )
        else:
            conn.commit()
        artifact_rollback.preserve()
        result = _group_result(
            anchor,
            cases,
            results,
            parsed.baseline_ok,
        )
    except (MachineQaProtocolError, TestMachineCapabilityError, ValueError) as exc:
        rollback_machine_submission(conn, artifact_rollback)
        return _failure("test_machine_baseline_group_submit_failed", str(exc))
    except Exception:
        rollback_machine_submission(conn, artifact_rollback)
        raise
    finally:
        conn.close()
    return HandlerOutcome(primary_success=True, result_payload=result)


__all__ = [
    "TestMachineBaselineGroupBeginResponse",
    "TestMachineBaselineGroupExecuteRequest",
    "TestMachineBaselineGroupExecuteResponse",
    "TestMachineBaselineGroupSubmitRequest",
    "_baseline_group_cases",
    "handle_baseline_group_begin",
    "handle_baseline_group_execute",
    "handle_baseline_group_submit",
]
