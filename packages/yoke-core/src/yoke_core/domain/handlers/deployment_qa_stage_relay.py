"""Server-side evaluation for scoped-QA stage dispatch and resume refusals.

The deploy driver runs wherever it was started, often with no local
database authority (an ordinary project deploy works over HTTPS only), so
``deployment_qa_stage_dispatch.dispatch_deployment_qa_stage`` and
``deployment_qa_stage_resume.resume_qa_refusal_message`` always relay here
instead of opening a connection client-side. This module is where the
verdict is actually computed, against the database that serves it.
"""

from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_core.domain.deployment_qa_stage_dispatch import (
    DISPATCH_DEPLOYMENT_QA_STAGE_FUNCTION as DISPATCH_FUNCTION_ID,
    materialize_and_gate_deployment_qa_stage,
)
from yoke_core.domain.deployment_qa_stage_resume import (
    RESUME_DEPLOYMENT_QA_REFUSALS_FUNCTION as RESUME_FUNCTION_ID,
    prior_deployment_qa_refusals,
)
from yoke_core.domain.handlers.deployment_common import error, run_id


class DeploymentQaStageDispatchRequest(BaseModel):
    stage: Dict[str, Any]


class DeploymentQaStageDispatchResponse(BaseModel):
    run_id: str
    code: int
    message: str


class DeploymentQaStageResumeRefusalsRequest(BaseModel):
    stages: List[Dict[str, Any]]
    start_stage: str


class DeploymentQaStageResumeRefusalsResponse(BaseModel):
    run_id: str
    message: str


def handle_deployment_qa_stage_dispatch(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    resolved = run_id(request, DISPATCH_FUNCTION_ID)
    if isinstance(resolved, HandlerOutcome):
        return resolved
    payload = request.payload or {}
    stage = payload.get("stage")
    if not isinstance(stage, dict) or not stage.get("name"):
        return error(
            "payload_invalid",
            f"{DISPATCH_FUNCTION_ID} requires payload.stage naming the stage",
            jsonpath="$.payload.stage",
        )
    from yoke_core.domain.db_helpers import connect

    conn = connect()
    try:
        code, message = materialize_and_gate_deployment_qa_stage(
            conn, stage, run_id=resolved
        )
    finally:
        conn.close()
    return HandlerOutcome(
        result_payload={"run_id": resolved, "code": code, "message": message},
        primary_success=True,
    )


def handle_deployment_qa_stage_resume_refusals(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    resolved = run_id(request, RESUME_FUNCTION_ID)
    if isinstance(resolved, HandlerOutcome):
        return resolved
    payload = request.payload or {}
    stages = payload.get("stages")
    start_stage = payload.get("start_stage")
    if not isinstance(stages, list):
        return error(
            "payload_invalid",
            f"{RESUME_FUNCTION_ID} requires payload.stages as a list",
            jsonpath="$.payload.stages",
        )
    if not isinstance(start_stage, str) or not start_stage.strip():
        return error(
            "payload_invalid",
            f"{RESUME_FUNCTION_ID} requires payload.start_stage",
            jsonpath="$.payload.start_stage",
        )
    from yoke_core.domain.db_helpers import connect

    conn = connect()
    try:
        refusals = prior_deployment_qa_refusals(
            conn, run_id=resolved, stages=stages, start_stage=start_stage.strip()
        )
    finally:
        conn.close()
    return HandlerOutcome(
        result_payload={"run_id": resolved, "message": "; ".join(refusals)},
        primary_success=True,
    )


__all__ = [
    "DeploymentQaStageDispatchRequest",
    "DeploymentQaStageDispatchResponse",
    "DeploymentQaStageResumeRefusalsRequest",
    "DeploymentQaStageResumeRefusalsResponse",
    "handle_deployment_qa_stage_dispatch",
    "handle_deployment_qa_stage_resume_refusals",
]
