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

from yoke_core.domain.deployment_qa_transaction_recovery import rollback_after_error

import json
from typing import Any, Dict, List, Union

from pydantic import BaseModel

from psycopg.errors import DeadlockDetected, LockNotAvailable, QueryCanceled

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_core.domain.deploy_pipeline_qa_wait import AWAITING_SCOPED_QA
from yoke_core.domain.deployment_runs_lock import RUN_BUSY_CODE, DeploymentRunBusy
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
    require_run_driver,
)


#: A cancelled statement (57014), a lock timeout (55P03), a deadlock victim
#: (40P01) or a run row still held past its bound (``run_busy``): the wait
#: ended, not the stage. Retrying the same dispatch is safe.
LOCK_WAIT_INTERRUPTIONS = (
    QueryCanceled,
    LockNotAvailable,
    DeadlockDetected,
    DeploymentRunBusy,
)


def interrupted_dispatch_wait(
    conn: Any, *, run_id: str, stage_name: str, exc: Exception
) -> str:
    """Name a lock wait that was cancelled or timed out; the run is not failed.

    Members settled before the interruption already committed. Answering the
    held QA wait keeps the run executing at this stage, so the driver
    re-dispatches the same stage instead of failing the run.
    """
    from yoke_core.domain.deployment_runs_lock import run_row_lock_holder

    holder = run_row_lock_holder(conn)
    who = (
        f"pid {holder.pid} has held a deployment_runs lock for "
        f"{holder.age_seconds}s{f' while {holder.state}' if holder.state else ''}"
        if holder is not None
        else "no other backend holds a deployment_runs lock now"
    )
    sqlstate = getattr(exc, "sqlstate", "")
    cause = (
        f"SQLSTATE {sqlstate}"
        if sqlstate
        else RUN_BUSY_CODE
        if isinstance(exc, DeploymentRunBusy)
        else type(exc).__name__
    )
    return (
        f"qa_stage_dispatch_interrupted: run {run_id!r} stage {stage_name!r} "
        f"stopped on a database lock wait that was cancelled or timed out "
        f"({cause}; {who}). Its transaction was rolled back, members "
        "settled before it keep their result, and the run stays executing at "
        "this stage; the driver re-dispatches the same stage. If it repeats, "
        "let the holder finish (an 'idle in transaction' holder is an abandoned "
        "client that releases on its own), then re-drive with "
        f"`yoke watch deploy -- {run_id}`."
    )


def _driven_run(request: FunctionCallRequest, function_id: str):
    resolved = run_id(request, function_id)
    if isinstance(resolved, HandlerOutcome):
        return resolved
    return require_run_driver(request, resolved) or resolved


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
    pending_plans: list[dict] = []


class DeploymentQaStageResumeRefusalsRequest(BaseModel):
    start_stage: str


class DeploymentQaStageResumeRefusalsResponse(BaseModel):
    run_id: str
    message: str


def handle_deployment_qa_stage_dispatch(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    resolved = _driven_run(request, DISPATCH_FUNCTION_ID)
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
        pending_plans = []
        try:
            code, message = materialize_and_gate_deployment_qa_stage(
                conn, stage, run_id=resolved
            )
            if code == AWAITING_SCOPED_QA:
                from yoke_core.domain.deployment_qa_pending_plans import pending_stage_plans

                pending_plans = pending_stage_plans(conn, stage, resolved)
        except LOCK_WAIT_INTERRUPTIONS as exc:
            rollback_after_error(conn, exc)
            code, message = (
                AWAITING_SCOPED_QA,
                interrupted_dispatch_wait(
                    conn, run_id=resolved, stage_name=str(stage["name"]), exc=exc
                ),
            )
    finally:
        conn.close()
    return HandlerOutcome(
        result_payload={"run_id": resolved, "code": code, "message": message,
                        "pending_plans": pending_plans},
        primary_success=True,
    )


def handle_deployment_qa_stage_resume_refusals(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    resolved = _driven_run(request, RESUME_FUNCTION_ID)
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
