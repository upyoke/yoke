"""Run-scoped durable stage-receipt bookkeeping for the client-local deploy pipeline."""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_core.domain.handlers.deployment_common import error, run_id
from yoke_core.domain.handlers.deployment_run_execution import (
    _require_execution_lock,
)


class DeploymentExecutionStageReceiptAllocateRequest(BaseModel):
    stage_name: str
    correlation_id: str
    target_kind: str
    executor: str


class DeploymentExecutionStageReceiptAllocateResponse(BaseModel):
    run_id: str
    receipt_id: int
    attempt_number: int
    status: str


class DeploymentExecutionStageReceiptCompleteRequest(BaseModel):
    receipt_id: int
    correlation_id: str
    status: str
    target_name: Optional[str] = None
    observed_url: Optional[str] = None
    observed_release_lineage: Optional[str] = None
    observed_artifact_identity: Optional[str] = None
    executor_receipt: Optional[str] = None
    failure_reason: Optional[str] = None


class DeploymentExecutionStageReceiptCompleteResponse(BaseModel):
    run_id: str
    receipt_id: int
    status: str


class DeploymentExecutionStageReceiptLatestRequest(BaseModel):
    stage_name: str


class DeploymentExecutionStageReceiptLatestResponse(BaseModel):
    run_id: str
    receipt: Optional[Dict[str, Any]] = None


def _locked_run(request: FunctionCallRequest, function_id: str):
    resolved = run_id(request, function_id)
    if isinstance(resolved, HandlerOutcome):
        return resolved
    return _require_execution_lock(request, resolved) or resolved


def handle_deployment_execution_stage_receipt_allocate(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    resolved = _locked_run(request, "deployment_runs.execution.stage_receipt_allocate")
    if isinstance(resolved, HandlerOutcome):
        return resolved
    payload = request.payload or {}
    stage_name = str(payload.get("stage_name") or "").strip()
    correlation_id = str(payload.get("correlation_id") or "").strip()
    target_kind = str(payload.get("target_kind") or "").strip()
    executor = str(payload.get("executor") or "").strip()
    if not stage_name or not correlation_id or not target_kind or not executor:
        return error(
            "payload_invalid",
            "stage_name, correlation_id, target_kind, and executor are required",
        )
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.deployment_stage_receipts import (
        allocate_deployment_stage_receipt,
    )

    try:
        with connect() as conn:
            receipt = allocate_deployment_stage_receipt(
                conn,
                run_id=resolved,
                stage_name=stage_name,
                correlation_id=correlation_id,
                target_kind=target_kind,
                executor=executor,
            )
    except (LookupError, ValueError) as exc:
        return error("stage_receipt_allocate_failed", str(exc))
    return HandlerOutcome(
        result_payload={
            "run_id": resolved,
            "receipt_id": int(receipt["id"]),
            "attempt_number": int(receipt["attempt_number"]),
            "status": str(receipt["status"]),
        },
        primary_success=True,
    )


def handle_deployment_execution_stage_receipt_complete(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    resolved = _locked_run(request, "deployment_runs.execution.stage_receipt_complete")
    if isinstance(resolved, HandlerOutcome):
        return resolved
    payload = request.payload or {}
    receipt_id = payload.get("receipt_id")
    correlation_id = str(payload.get("correlation_id") or "").strip()
    status = str(payload.get("status") or "").strip()
    if receipt_id is None or not correlation_id or not status:
        return error(
            "payload_invalid",
            "receipt_id, correlation_id, and status are required",
        )
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.deployment_stage_receipts import (
        complete_deployment_stage_receipt,
    )

    try:
        with connect() as conn:
            receipt = complete_deployment_stage_receipt(
                conn,
                run_id=resolved,
                receipt_id=int(receipt_id),
                correlation_id=correlation_id,
                status=status,
                target_name=payload.get("target_name"),
                observed_url=payload.get("observed_url"),
                observed_release_lineage=payload.get("observed_release_lineage"),
                observed_artifact_identity=payload.get("observed_artifact_identity"),
                executor_receipt=payload.get("executor_receipt"),
                failure_reason=payload.get("failure_reason"),
            )
    except (LookupError, ValueError) as exc:
        return error("stage_receipt_complete_failed", str(exc))
    return HandlerOutcome(
        result_payload={
            "run_id": resolved,
            "receipt_id": int(receipt["id"]),
            "status": str(receipt["status"]),
        },
        primary_success=True,
    )


def handle_deployment_execution_stage_receipt_latest(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    """Return the newest receipt attempt for a stage, or ``None`` if absent.

    Used to decide, before allocating, whether a dispatch is a transport
    retry of an in-flight attempt (reuse its correlation) or an intentional
    new physical attempt (mint a fresh one) — never both from the same call.
    """
    resolved = _locked_run(request, "deployment_runs.execution.stage_receipt_latest")
    if isinstance(resolved, HandlerOutcome):
        return resolved
    stage_name = str((request.payload or {}).get("stage_name") or "").strip()
    if not stage_name:
        return error("payload_invalid", "stage_name is required")
    from yoke_core.domain.db_helpers import connect

    with connect() as conn:
        cursor = conn.execute(
            "SELECT id,attempt_number,correlation_id,status FROM "
            "deployment_stage_receipts WHERE run_id=%s AND stage_name=%s "
            "ORDER BY attempt_number DESC LIMIT 1",
            (resolved, stage_name),
        )
        row = cursor.fetchone()
        receipt = (
            {
                "id": int(row[0]),
                "attempt_number": int(row[1]),
                "correlation_id": str(row[2]),
                "status": str(row[3]),
            }
            if row is not None
            else None
        )
    return HandlerOutcome(
        result_payload={"run_id": resolved, "receipt": receipt},
        primary_success=True,
    )


__all__ = [
    "DeploymentExecutionStageReceiptAllocateRequest",
    "DeploymentExecutionStageReceiptAllocateResponse",
    "DeploymentExecutionStageReceiptCompleteRequest",
    "DeploymentExecutionStageReceiptCompleteResponse",
    "DeploymentExecutionStageReceiptLatestRequest",
    "DeploymentExecutionStageReceiptLatestResponse",
    "handle_deployment_execution_stage_receipt_allocate",
    "handle_deployment_execution_stage_receipt_complete",
    "handle_deployment_execution_stage_receipt_latest",
]
