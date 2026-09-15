"""Run-scoped QA bookkeeping for the client-local deploy pipeline."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_core.domain.handlers.deployment_common import error, run_id
from yoke_core.domain.handlers.deployment_run_execution import (
    _require_execution_lock,
)


class DeploymentExecutionQaSeedRequest(BaseModel):
    pass


class DeploymentExecutionQaSeedResponse(BaseModel):
    run_id: str
    seeded: int


class DeploymentExecutionQaRecordRequest(BaseModel):
    stage: str
    verdict: str
    raw_result: str = "{}"
    duration_ms: Optional[str] = None
    workflow_run: Optional[str] = None


class DeploymentExecutionQaRecordResponse(BaseModel):
    run_id: str
    stage: str
    qa_run_id: Optional[str] = None


class DeploymentExecutionQaPendingRequest(BaseModel):
    pass


class DeploymentExecutionQaPendingResponse(BaseModel):
    run_id: str
    unresolved: List[str]


class DeploymentExecutionEphemeralQaReadyRequest(BaseModel):
    pass


class DeploymentExecutionEphemeralQaReadyResponse(BaseModel):
    run_id: str
    ready: bool


def _locked_run(request: FunctionCallRequest, function_id: str):
    resolved = run_id(request, function_id)
    if isinstance(resolved, HandlerOutcome):
        return resolved
    return _require_execution_lock(request, resolved) or resolved


def handle_deployment_execution_qa_seed(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    resolved = _locked_run(request, "deployment_runs.execution.qa_seed")
    if isinstance(resolved, HandlerOutcome):
        return resolved
    from yoke_core.domain.deploy_qa_recorder import cmd_seed_from_flow

    seeded = cmd_seed_from_flow(resolved)
    if seeded < 0:
        return error("qa_seed_failed", f"could not seed QA for run {resolved}")
    return HandlerOutcome(
        result_payload={"run_id": resolved, "seeded": seeded},
        primary_success=True,
    )


def handle_deployment_execution_qa_record(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    resolved = _locked_run(request, "deployment_runs.execution.qa_record")
    if isinstance(resolved, HandlerOutcome):
        return resolved
    payload = request.payload or {}
    stage = str(payload.get("stage") or "").strip()
    verdict = str(payload.get("verdict") or "").strip()
    if not stage or not verdict:
        return error("payload_invalid", "stage and verdict are required")
    from yoke_core.domain.deploy_qa_recorder import cmd_record_stage_result

    try:
        qa_run_id = cmd_record_stage_result(
            resolved,
            stage,
            verdict,
            raw_result=str(payload.get("raw_result") or "{}"),
            duration_ms=payload.get("duration_ms"),
            workflow_run=payload.get("workflow_run"),
        )
    except RuntimeError as exc:
        return error("qa_record_failed", str(exc))
    return HandlerOutcome(
        result_payload={
            "run_id": resolved,
            "stage": stage,
            "qa_run_id": str(qa_run_id) if qa_run_id is not None else None,
        },
        primary_success=True,
    )


def handle_deployment_execution_qa_pending(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    resolved = _locked_run(request, "deployment_runs.execution.qa_pending")
    if isinstance(resolved, HandlerOutcome):
        return resolved
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.deployment_run_completion_preconditions import (
        unresolved_blocking_qa,
    )

    with connect() as conn:
        unresolved = unresolved_blocking_qa(conn, resolved)
    return HandlerOutcome(
        result_payload={"run_id": resolved, "unresolved": unresolved},
        primary_success=True,
    )


def handle_deployment_execution_ephemeral_qa_ready(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    resolved = _locked_run(request, "deployment_runs.execution.ephemeral_qa_ready")
    if isinstance(resolved, HandlerOutcome):
        return resolved
    from yoke_core.domain.db_helpers import connect, query_scalar
    from yoke_core.domain.qa_constants import browser_requirement_predicate

    with connect() as conn:
        missing = query_scalar(
            conn,
            "SELECT COUNT(*) FROM deployment_run_items dri "
            "WHERE dri.run_id=%s AND NOT EXISTS ("
            "SELECT 1 FROM qa_runs qr JOIN qa_requirements qreq "
            "ON qr.qa_requirement_id=qreq.id "
            "WHERE qreq.item_id=dri.item_id AND "
            f"{browser_requirement_predicate('qreq')} "
            "AND qreq.qa_phase='verification' AND qr.verdict='pass')",
            (resolved,),
        )
    return HandlerOutcome(
        result_payload={"run_id": resolved, "ready": int(missing or 0) == 0},
        primary_success=True,
    )


__all__ = [
    "DeploymentExecutionQaPendingRequest",
    "DeploymentExecutionQaPendingResponse",
    "DeploymentExecutionEphemeralQaReadyRequest",
    "DeploymentExecutionEphemeralQaReadyResponse",
    "DeploymentExecutionQaRecordRequest",
    "DeploymentExecutionQaRecordResponse",
    "DeploymentExecutionQaSeedRequest",
    "DeploymentExecutionQaSeedResponse",
    "handle_deployment_execution_qa_pending",
    "handle_deployment_execution_qa_record",
    "handle_deployment_execution_qa_seed",
    "handle_deployment_execution_ephemeral_qa_ready",
]
