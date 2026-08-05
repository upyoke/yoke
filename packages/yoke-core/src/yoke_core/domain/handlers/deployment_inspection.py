"""Deployment flow inventory and item/run inspection handlers."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_core.domain.handlers.deployment_common import (
    FLOW_ROW_FIELDS,
    error,
    pipe_to_dict,
    require_global,
    run_id,
)


class DeploymentFlowListRequest(BaseModel):
    project: Optional[str] = None
    include_disabled: bool = False


class DeploymentFlowListResponse(BaseModel):
    fields: List[str]
    rows: List[Dict[str, Any]]


class DeploymentRunsFindByItemRequest(BaseModel):
    status: Optional[str] = None


class DeploymentRunsFindByItemResponse(BaseModel):
    item_id: int
    fields: List[str]
    rows: List[Dict[str, Any]]


class DeploymentRunStagesRequest(BaseModel):
    pass


class DeploymentRunStagesResponse(BaseModel):
    run_id: str
    flow: str
    status: str
    current_stage: str
    stages: List[Dict[str, Any]]


def _pipe_rows(raw: str, fields: tuple[str, ...]) -> List[Dict[str, Any]]:
    return [
        pipe_to_dict(line, fields)
        for line in raw.splitlines()
        if line.strip()
    ]


def handle_deployment_flow_list(request: FunctionCallRequest) -> HandlerOutcome:
    invalid = require_global(request, "deployment_flows.list")
    if invalid is not None:
        return invalid
    payload = DeploymentFlowListRequest.model_validate(request.payload or {})

    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.flow import cmd_list

    try:
        with connect() as conn:
            raw = cmd_list(
                conn,
                payload.project,
                include_disabled=payload.include_disabled,
            )
    except LookupError as exc:
        return error("not_found", str(exc), jsonpath="$.payload.project")
    return HandlerOutcome(
        result_payload={
            "fields": list(FLOW_ROW_FIELDS),
            "rows": _pipe_rows(raw, FLOW_ROW_FIELDS),
        },
        primary_success=True,
    )


def handle_deployment_runs_find_by_item(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    if request.target.kind != "item" or request.target.item_id is None:
        return error(
            "target_invalid",
            "deployment_runs.find_by_item requires a resolved item target",
            jsonpath="$.target",
        )
    payload = DeploymentRunsFindByItemRequest.model_validate(request.payload or {})

    from yoke_core.domain.deployment_runs_crud_query import cmd_find_by_item

    fields = ("id", "status", "current_stage", "created_at")
    raw = cmd_find_by_item(int(request.target.item_id), status=payload.status)
    return HandlerOutcome(
        result_payload={
            "item_id": int(request.target.item_id),
            "fields": list(fields),
            "rows": _pipe_rows(raw, fields),
        },
        primary_success=True,
    )


def _stage_state(
    *, index: int, current_index: int, run_status: str
) -> str:
    if run_status == "succeeded":
        return "completed"
    if index < current_index:
        return "completed"
    if index == current_index:
        return "failed" if run_status == "failed" else "current"
    return "pending"


def handle_deployment_run_stages(request: FunctionCallRequest) -> HandlerOutcome:
    resolved_run_id = run_id(request, "deployment_runs.stages")
    if isinstance(resolved_run_id, HandlerOutcome):
        return resolved_run_id

    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain import db_backend

    with connect() as conn:
        marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
        row = conn.execute(
            "SELECT dr.flow, dr.status, COALESCE(dr.current_stage, ''), df.stages "
            "FROM deployment_runs dr JOIN deployment_flows df ON df.id = dr.flow "
            f"WHERE dr.id = {marker}",
            (resolved_run_id,),
        ).fetchone()
    if row is None:
        return error("not_found", f"deployment run {resolved_run_id!r} not found")
    raw_stages = json.loads(str(row[3]))
    current = str(row[2] or "")
    current_index = next(
        (
            index
            for index, stage in enumerate(raw_stages)
            if str(stage.get("name") or "") == current
        ),
        -1,
    )
    stages = [
        {
            **stage,
            "position": index + 1,
            "state": _stage_state(
                index=index,
                current_index=current_index,
                run_status=str(row[1]),
            ),
        }
        for index, stage in enumerate(raw_stages)
    ]
    return HandlerOutcome(
        result_payload={
            "run_id": resolved_run_id,
            "flow": str(row[0]),
            "status": str(row[1]),
            "current_stage": current,
            "stages": stages,
        },
        primary_success=True,
    )


__all__ = [
    "DeploymentFlowListRequest",
    "DeploymentFlowListResponse",
    "DeploymentRunStagesRequest",
    "DeploymentRunStagesResponse",
    "DeploymentRunsFindByItemRequest",
    "DeploymentRunsFindByItemResponse",
    "handle_deployment_flow_list",
    "handle_deployment_run_stages",
    "handle_deployment_runs_find_by_item",
]
