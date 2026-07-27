"""Registered execution and evidence recording for Machine QA cases."""

from __future__ import annotations

import time
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_core.domain.handlers.test_machine import _failure
from yoke_core.domain.handlers.test_machine_case_evidence import (
    record_machine_case_result as _record_machine_case_result,
)
from yoke_core.domain.test_machine_capability import TestMachineCapabilityError


class TestMachineCaseExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TestMachineCaseExecuteResponse(BaseModel):
    requirement_id: int
    executor_id: str
    verdict: str | None
    case_outcome: str
    run_id: int
    evidence_count: int
    capture_degraded_reason: str | None
    error_code: str | None
    lease_context: dict[str, Any] | None = None


class TestMachineBaselineGroupExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TestMachineBaselineGroupExecuteResponse(BaseModel):
    anchor_requirement_id: int
    plan_id: int
    host_baseline: str
    baseline_ok: bool | None
    requirement_ids: list[int]
    results: list[TestMachineCaseExecuteResponse]


def _is_machine_case(case: dict[str, Any]) -> bool:
    from yoke_core.domain.machine_qa_method_contracts import MACHINE_METHODS

    return (
        case["executor_id"] == "host_control" and case["method_id"] in MACHINE_METHODS
    )


def _baseline_group_cases(
    conn: Any,
    *,
    anchor: dict[str, Any],
) -> list[dict[str, Any]]:
    """Reread one materialized baseline group from database authority."""
    from yoke_core.domain import db_backend
    from yoke_core.domain.machine_qa_method_contracts import MACHINE_METHODS
    from yoke_core.domain.qa_case_execution_context import (
        get_case_execution_context,
    )

    plan_id = anchor.get("plan_id")
    baseline = str(anchor.get("host_baseline") or "")
    if plan_id is None or not baseline:
        raise ValueError(
            "baseline-group execution requires a plan-backed Machine QA "
            "requirement with a host baseline"
        )
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    method_ids = sorted(MACHINE_METHODS)
    method_markers = ", ".join(marker for _ in method_ids)
    rows = conn.execute(
        "SELECT id FROM qa_requirements "
        f"WHERE item_id={marker} AND plan_id={marker} "
        f"AND COALESCE(workflow_transition_id, '')={marker} "
        f"AND host_baseline={marker} AND waived_at IS NULL "
        f"AND method_id IN ({method_markers}) "
        "ORDER BY id",
        (
            int(anchor["item_id"]),
            int(plan_id),
            str(anchor.get("workflow_transition_id") or ""),
            baseline,
            *method_ids,
        ),
    ).fetchall()
    cases = [
        get_case_execution_context(conn, requirement_id=int(row[0])) for row in rows
    ]
    anchor_id = int(anchor["requirement_id"])
    if not cases or anchor_id not in {int(case["requirement_id"]) for case in cases}:
        raise ValueError(
            "the targeted requirement is not in its materialized baseline group"
        )
    for case in cases:
        if not _is_machine_case(case):
            raise ValueError(
                "the materialized baseline group contains an unregistered "
                "Machine QA case"
            )
        if (
            int(case["item_id"]) != int(anchor["item_id"])
            or int(case["plan_id"]) != int(plan_id)
            or str(case.get("workflow_transition_id") or "")
            != str(anchor.get("workflow_transition_id") or "")
            or str(case.get("host_baseline") or "") != baseline
        ):
            raise ValueError("the materialized baseline group changed during execution")
    return cases


def handle_case_execute(request: FunctionCallRequest) -> HandlerOutcome:
    try:
        TestMachineCaseExecuteRequest.model_validate(request.payload or {})
    except ValidationError as exc:
        return _failure("payload_invalid", str(exc))
    requirement_id = request.target.qa_requirement_id
    if request.target.kind != "qa_requirement" or requirement_id is None:
        return _failure(
            "target_invalid",
            "test_machine.case_execute requires target.kind='qa_requirement'",
        )
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.machine_qa_execution import (
        MachineQaLeaseHeld,
        acquire_machine_qa_lease,
    )
    from yoke_core.domain.machine_qa_method_contracts import (
        MachineQaExecutionError,
    )
    from yoke_core.domain.qa_case_execution_context import (
        QaCaseExecutionError,
        get_case_execution_context,
    )

    conn = connect()
    try:
        case = get_case_execution_context(
            conn,
            requirement_id=int(requirement_id),
        )
        if not _is_machine_case(case):
            return _failure(
                "test_machine_case_invalid",
                "the requirement is not a registered Machine QA case",
            )
        started = time.monotonic()
        try:
            with acquire_machine_qa_lease(
                conn,
                project=str(case["project"]),
                session_id=request.actor.session_id,
                actor_id=request.actor.actor_id,
            ) as execution:
                if case.get("host_baseline"):
                    execution.reach_baseline(str(case["host_baseline"]))
                result = execution.execute(
                    method_id=str(case["method_id"]),
                    method_config=case["method_config"],
                    entry_surface=case.get("entry_surface"),
                    required_completion=case.get("required_completion"),
                )
        except MachineQaLeaseHeld as held:
            result = held.waiting_result()
        payload = _record_machine_case_result(
            conn,
            case=case,
            result=result,
            duration_ms=int((time.monotonic() - started) * 1000),
        )
    except (
        QaCaseExecutionError,
        MachineQaExecutionError,
        TestMachineCapabilityError,
        ValueError,
    ) as exc:
        conn.rollback()
        return _failure("test_machine_case_failed", str(exc))
    finally:
        conn.close()
    return HandlerOutcome(primary_success=True, result_payload=payload)


def handle_baseline_group_execute(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    """Execute one server-discovered baseline group under one host lease."""
    try:
        TestMachineBaselineGroupExecuteRequest.model_validate(
            request.payload or {},
        )
    except ValidationError as exc:
        return _failure("payload_invalid", str(exc))
    requirement_id = request.target.qa_requirement_id
    if request.target.kind != "qa_requirement" or requirement_id is None:
        return _failure(
            "target_invalid",
            "test_machine.baseline_group_execute requires target.kind='qa_requirement'",
        )
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.machine_qa_execution import (
        MachineQaLeaseHeld,
        acquire_machine_qa_lease,
    )
    from yoke_core.domain.machine_qa_method_contracts import (
        MachineQaExecutionError,
    )
    from yoke_core.domain.qa_case_execution_context import (
        QaCaseExecutionError,
        get_case_execution_context,
    )

    conn = connect()
    try:
        anchor = get_case_execution_context(
            conn,
            requirement_id=int(requirement_id),
        )
        if not _is_machine_case(anchor):
            return _failure(
                "test_machine_baseline_group_invalid",
                "the requirement is not a registered Machine QA case",
            )
        cases = _baseline_group_cases(conn, anchor=anchor)
        baseline = str(anchor["host_baseline"])
        payloads: list[dict[str, Any]] = []
        try:
            with acquire_machine_qa_lease(
                conn,
                project=str(anchor["project"]),
                session_id=request.actor.session_id,
                actor_id=request.actor.actor_id,
            ) as execution:
                execution.reach_baseline(baseline)
                for case in cases:
                    started = time.monotonic()
                    result = execution.execute(
                        method_id=str(case["method_id"]),
                        method_config=case["method_config"],
                        entry_surface=case.get("entry_surface"),
                        required_completion=case.get("required_completion"),
                    )
                    payloads.append(
                        _record_machine_case_result(
                            conn,
                            case=case,
                            result=result,
                            duration_ms=int((time.monotonic() - started) * 1000),
                        )
                    )
                baseline_ok = bool(
                    execution.baseline is not None and execution.baseline.ok
                )
        except MachineQaLeaseHeld as held:
            baseline_ok = None
            for case in cases:
                started = time.monotonic()
                result = held.waiting_result()
                payloads.append(
                    _record_machine_case_result(
                        conn,
                        case=case,
                        result=result,
                        duration_ms=int((time.monotonic() - started) * 1000),
                    )
                )
        result_payload = {
            "anchor_requirement_id": int(requirement_id),
            "plan_id": int(anchor["plan_id"]),
            "host_baseline": baseline,
            "baseline_ok": baseline_ok,
            "requirement_ids": [int(case["requirement_id"]) for case in cases],
            "results": payloads,
        }
    except (
        QaCaseExecutionError,
        MachineQaExecutionError,
        TestMachineCapabilityError,
        ValueError,
    ) as exc:
        conn.rollback()
        return _failure("test_machine_baseline_group_failed", str(exc))
    finally:
        conn.close()
    return HandlerOutcome(
        primary_success=True,
        result_payload=result_payload,
    )


__all__ = [
    "TestMachineBaselineGroupExecuteRequest",
    "TestMachineBaselineGroupExecuteResponse",
    "TestMachineCaseExecuteRequest",
    "TestMachineCaseExecuteResponse",
    "handle_baseline_group_execute",
    "handle_case_execute",
]
