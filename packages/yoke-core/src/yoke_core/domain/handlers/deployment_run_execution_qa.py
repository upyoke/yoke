"""Run-scoped QA bookkeeping for the client-local deploy pipeline."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_core.domain.handlers.deployment_common import run_id
from yoke_core.domain.handlers.deployment_run_execution import (
    require_run_driver,
)


class DeploymentExecutionQaPendingRequest(BaseModel):
    stage_name: Optional[str] = None


class DeploymentExecutionQaPendingResponse(BaseModel):
    run_id: str
    unresolved: List[str]
    held_report: Optional[List[str]] = None


class DeploymentExecutionEphemeralQaReadyRequest(BaseModel):
    pass


class DeploymentExecutionEphemeralQaReadyResponse(BaseModel):
    run_id: str
    ready: bool


def _driven_run(request: FunctionCallRequest, function_id: str):
    resolved = run_id(request, function_id)
    if isinstance(resolved, HandlerOutcome):
        return resolved
    return require_run_driver(request, resolved) or resolved


def handle_deployment_execution_qa_pending(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    resolved = _driven_run(request, "deployment_runs.execution.qa_pending")
    if isinstance(resolved, HandlerOutcome):
        return resolved
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.deployment_run_completion_preconditions import (
        held_stage_report_lines,
        unresolved_blocking_qa,
    )
    from yoke_core.domain.deployment_qa_stage_outstanding import qa_stage_outstanding

    with connect() as conn:
        unresolved = unresolved_blocking_qa(conn, resolved)
        result = {"run_id": resolved, "unresolved": unresolved}
        stage_name = str((request.payload or {}).get("stage_name") or "")
        if stage_name:
            scoped = qa_stage_outstanding(conn, run_id=resolved, stage_name=stage_name)
            details = [*unresolved, *(scoped.lines if scoped else ())]
            count = len(unresolved) + (scoped.waiting if scoped else 0)
            result["held_report"] = held_stage_report_lines(
                resolved, stage_name, details, obligation_count=count
            )
    return HandlerOutcome(
        result_payload=result,
        primary_success=True,
    )


def handle_deployment_execution_ephemeral_qa_ready(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    resolved = _driven_run(request, "deployment_runs.execution.ephemeral_qa_ready")
    if isinstance(resolved, HandlerOutcome):
        return resolved
    from yoke_core.domain.db_helpers import connect, query_scalar
    from yoke_core.domain.qa_constants import browser_requirement_predicate
    from yoke_core.domain.qa_latest_execution import latest_execution_id_sql
    from yoke_core.domain.qa_obligation_settlement import settled_obligation_sql
    from yoke_core.domain.qa_browser_evidence_check import _browser_proof_exists

    with connect() as conn:
        missing = query_scalar(
            conn,
            "SELECT COUNT(*) FROM deployment_run_items dri "
            "WHERE dri.run_id=%s AND NOT EXISTS ("
            "SELECT 1 FROM qa_runs qr JOIN qa_requirements qreq "
            "ON qr.qa_requirement_id=qreq.id "
            "WHERE qreq.item_id=dri.item_id AND "
            f"{browser_requirement_predicate('qreq')} "
            f"AND qr.id=({latest_execution_id_sql('qreq.id')}) "
            f"AND NOT {settled_obligation_sql(conn, 'qreq')} "
            f"AND {_browser_proof_exists('qreq')} "
            "AND qreq.qa_phase='verification' AND qr.verdict='pass' AND qr.completed_at IS NOT NULL)",
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
    "handle_deployment_execution_qa_pending",
    "handle_deployment_execution_ephemeral_qa_ready",
]
