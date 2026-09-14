"""Run-scoped authority for the existing client-local deploy pipeline."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_core.domain.handlers.deployment_common import error, pipe_to_dict, run_id


class DeploymentExecutionContextRequest(BaseModel):
    pass


class DeploymentExecutionContextResponse(BaseModel):
    run: Dict[str, Any]
    members: List[Dict[str, Any]]
    stages: List[Dict[str, Any]]


class DeploymentExecutionUpdateRequest(BaseModel):
    field: str
    value: str


class DeploymentExecutionUpdateResponse(BaseModel):
    run_id: str
    field: str
    value: str
    updated: bool


def _require_execution_lock(
    request: FunctionCallRequest, resolved_run_id: str
) -> Optional[HandlerOutcome]:
    from yoke_core.domain.db_helpers import connect, query_scalar
    from yoke_core.domain.deploy_lock import DeployLockError, require_deploy_lock

    with connect() as conn:
        project_id = query_scalar(
            conn,
            "SELECT project_id FROM deployment_runs WHERE id=%s",
            (resolved_run_id,),
        )
        if project_id is None:
            return error("not_found", f"deployment run {resolved_run_id!r} not found")
        try:
            require_deploy_lock(
                conn,
                int(project_id),
                session_id=request.actor.session_id,
                operation="deployment run execution",
            )
        except DeployLockError as exc:
            return error("deploy_lock_required", str(exc))
    return None


def _member_rows(run_id_value: str) -> List[Dict[str, Any]]:
    from yoke_core.domain.db_helpers import connect, query_rows
    from yoke_core.domain.item_worktrees import primary_item_worktree
    from yoke_core.domain.project_identity import render_item_ref

    with connect() as conn:
        rows = query_rows(
            conn,
            "SELECT dri.item_id,i.status,dri.delivery_intent,"
            "dri.requirement_snapshot FROM deployment_run_items dri "
            "JOIN items i ON i.id=dri.item_id WHERE dri.run_id=%s "
            "ORDER BY dri.item_id",
            (run_id_value,),
        )
        members = []
        for row in rows:
            item_id = int(row["item_id"])
            lane = primary_item_worktree(conn, item_id) or {}
            members.append(
                {
                    "item_id": item_id,
                    "public_ref": render_item_ref(conn, item_id),
                    "status": str(row["status"]),
                    "branch": str(lane.get("branch") or ""),
                    "delivery_intent": row.get("delivery_intent"),
                    "requirement_snapshot": row.get("requirement_snapshot"),
                }
            )
        return members


def handle_deployment_execution_context(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    resolved_run_id = run_id(request, "deployment_runs.execution.context")
    if isinstance(resolved_run_id, HandlerOutcome):
        return resolved_run_id
    if refusal := _require_execution_lock(request, resolved_run_id):
        return refusal
    from yoke_core.domain.deployment_run_carried_work import parse_carried_work
    from yoke_core.domain.deployment_runs_crud_query import cmd_get
    from yoke_core.domain.deployment_runs_schema import RUN_FIELDS
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.flow import cmd_stages

    raw = cmd_get(resolved_run_id)
    if raw is None:
        return error("not_found", f"deployment run {resolved_run_id!r} not found")
    run = pipe_to_dict(raw, RUN_FIELDS)
    run["carried_work"] = parse_carried_work(run.get("carried_work"))
    try:
        with connect() as conn:
            stages = json.loads(cmd_stages(conn, str(run["flow"])))
    except (LookupError, ValueError, json.JSONDecodeError) as exc:
        return error("execution_context_invalid", str(exc))
    return HandlerOutcome(
        result_payload={
            "run": run,
            "members": _member_rows(resolved_run_id),
            "stages": stages,
        },
        primary_success=True,
    )


def handle_deployment_execution_update(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    resolved_run_id = run_id(request, "deployment_runs.execution.update")
    if isinstance(resolved_run_id, HandlerOutcome):
        return resolved_run_id
    payload = request.payload or {}
    field = str(payload.get("field") or "").strip()
    value = payload.get("value")
    if field not in {"status", "current_stage"}:
        return error(
            "invalid_field",
            "execution updates are limited to status and current_stage",
            jsonpath="$.payload.field",
        )
    if value is None:
        return error("payload_invalid", "value is required", jsonpath="$.payload.value")
    if refusal := _require_execution_lock(request, resolved_run_id):
        return refusal
    from yoke_core.domain.deployment_runs_crud_mutate import cmd_update

    if update_error := cmd_update(resolved_run_id, field, str(value)):
        return error("update_failed", update_error)
    return HandlerOutcome(
        result_payload={
            "run_id": resolved_run_id,
            "field": field,
            "value": str(value),
            "updated": True,
        },
        primary_success=True,
    )


__all__ = [
    "DeploymentExecutionContextRequest",
    "DeploymentExecutionContextResponse",
    "DeploymentExecutionUpdateRequest",
    "DeploymentExecutionUpdateResponse",
    "_require_execution_lock",
    "handle_deployment_execution_context",
    "handle_deployment_execution_update",
]
