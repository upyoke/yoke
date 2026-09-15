"""Server-side evaluation for scoped-QA stage dispatch and resume refusals.

The deploy driver runs wherever it was started, often with no local
database authority (an ordinary project deploy works over HTTPS only), so
``deployment_qa_stage_dispatch.dispatch_deployment_qa_stage`` and
``deployment_qa_stage_resume.resume_qa_refusal_message`` reach these
handlers through the connection-keyed function-call dispatcher — locally
in-process for an admin-bootstrapped driver, relayed for an ordinary HTTPS
one. This module is where the verdict is actually computed, against the
database that serves it, and where every caller-supplied stage name is
resolved against the run's own stored flow rather than trusted verbatim.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Union

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
from yoke_core.domain.handlers.deployment_run_execution import (
    _require_execution_lock,
)


def _locked_run(request: FunctionCallRequest, function_id: str):
    resolved = run_id(request, function_id)
    if isinstance(resolved, HandlerOutcome):
        return resolved
    return _require_execution_lock(request, resolved) or resolved


def _stored_stages_for_run(
    conn: Any, resolved: str
) -> Union[List[Dict[str, Any]], HandlerOutcome]:
    """Read the run's own flow-derived stage list — never the caller's copy.

    A client-supplied stage (or stage list) is data a caller could omit or
    alter; every scoped-QA check evaluates against what the run's stored
    flow actually declares.
    """
    from yoke_core.domain.deployment_runs_crud_query import cmd_get
    from yoke_core.domain.flow import cmd_stages

    flow_id = cmd_get(resolved, "flow")
    if not flow_id:
        return error("not_found", f"deployment run {resolved!r} has no flow")
    try:
        return json.loads(cmd_stages(conn, flow_id))
    except LookupError as exc:
        return error("not_found", str(exc))


class DeploymentQaStageDispatchRequest(BaseModel):
    stage_name: str


class DeploymentQaStageDispatchResponse(BaseModel):
    run_id: str
    code: int
    message: str


class DeploymentQaStageResumeRefusalsRequest(BaseModel):
    start_stage: str


class DeploymentQaStageResumeRefusalsResponse(BaseModel):
    run_id: str
    message: str


def handle_deployment_qa_stage_dispatch(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    resolved = _locked_run(request, DISPATCH_FUNCTION_ID)
    if isinstance(resolved, HandlerOutcome):
        return resolved
    payload = request.payload or {}
    stage_name = payload.get("stage_name")
    if not isinstance(stage_name, str) or not stage_name.strip():
        return error(
            "payload_invalid",
            f"{DISPATCH_FUNCTION_ID} requires payload.stage_name",
            jsonpath="$.payload.stage_name",
        )
    from yoke_core.domain.db_helpers import connect

    conn = connect()
    try:
        # The stage's scope/config is derived from the run's own stored
        # flow, never trusted from the caller: a client-supplied stage
        # object could name a scope the run's real flow never declared.
        stages = _stored_stages_for_run(conn, resolved)
        if isinstance(stages, HandlerOutcome):
            return stages
        stage = next((s for s in stages if s.get("name") == stage_name.strip()), None)
        if stage is None:
            return error(
                "not_found",
                f"deployment run {resolved!r} has no stage named {stage_name!r}",
            )
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
    resolved = _locked_run(request, RESUME_FUNCTION_ID)
    if isinstance(resolved, HandlerOutcome):
        return resolved
    payload = request.payload or {}
    start_stage = payload.get("start_stage")
    if not isinstance(start_stage, str) or not start_stage.strip():
        return error(
            "payload_invalid",
            f"{RESUME_FUNCTION_ID} requires payload.start_stage",
            jsonpath="$.payload.start_stage",
        )
    from yoke_core.domain.db_helpers import connect

    conn = connect()
    try:
        stages = _stored_stages_for_run(conn, resolved)
        if isinstance(stages, HandlerOutcome):
            return stages
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
