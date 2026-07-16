"""Shared deployment handler models and row helpers."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


FLOW_ROW_FIELDS = (
    "id", "project", "name", "description", "stages", "on_failure",
    "created_at", "target_env", "done_description", "status",
)


class DeploymentFlowSetStatusRequest(BaseModel):
    flow_id: str
    status: str


class DeploymentFlowSetStatusResponse(BaseModel):
    flow_id: str
    status: str


class DeploymentFlowGetRequest(BaseModel):
    flow_id: str
    field: Optional[str] = None


class DeploymentFlowGetResponse(BaseModel):
    flow_id: str
    field: Optional[str] = None
    value: Optional[str] = None
    fields: Optional[List[str]] = None
    flow: Optional[Dict[str, Any]] = None


class DeploymentFlowStagesRequest(BaseModel):
    flow_id: str


class DeploymentFlowStagesResponse(BaseModel):
    flow_id: str
    stages: str


class DeploymentRunGetRequest(BaseModel):
    field: Optional[str] = None
    run_id: Optional[str] = None


class DeploymentRunGetResponse(BaseModel):
    run_id: str
    field: Optional[str] = None
    value: Optional[str] = None
    fields: Optional[List[str]] = None
    run: Optional[Dict[str, Any]] = None


class DeploymentRunListRequest(BaseModel):
    project: Optional[str] = None
    status: Optional[str] = None


class DeploymentRunListResponse(BaseModel):
    fields: List[str]
    rows: List[Dict[str, Any]]


class DeploymentRunUpdateRequest(BaseModel):
    field: str
    value: str
    force: bool = False
    run_id: Optional[str] = None


class DeploymentRunUpdateResponse(BaseModel):
    run_id: str
    field: str
    value: str
    updated: bool


class DeploymentRunResolveTargetEnvRequest(BaseModel):
    project: str
    flow: str
    target_env: Optional[str] = None


class DeploymentRunResolveTargetEnvResponse(BaseModel):
    project: str
    flow: str
    target_env: str


def error(
    code: str,
    message: str,
    *,
    jsonpath: Optional[str] = None,
) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath=jsonpath),
    )


def require_global(
    request: FunctionCallRequest,
    function_id: str,
) -> Optional[HandlerOutcome]:
    if request.target.kind == "global":
        return None
    return error(
        "target_invalid",
        f"{function_id} requires target.kind='global'",
        jsonpath="$.target.kind",
    )


def run_id(request: FunctionCallRequest, function_id: str) -> str | HandlerOutcome:
    payload = request.payload or {}
    value = request.target.workflow_run_id or payload.get("run_id")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return error(
        "target_invalid",
        f"{function_id} requires target.workflow_run_id",
        jsonpath="$.target.workflow_run_id",
    )


def flow_id(payload: Dict[str, Any], function_id: str) -> str | HandlerOutcome:
    value = payload.get("flow_id")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return error(
        "payload_invalid",
        f"{function_id} requires payload.flow_id",
        jsonpath="$.payload.flow_id",
    )


def pipe_to_dict(raw: str, fields: tuple[str, ...]) -> Dict[str, Any]:
    return {
        name: (value if value != "" else None)
        for name, value in zip(fields, raw.split("|"))
    }


def pipe_rows(raw: str, fields: tuple[str, ...]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for line in raw.splitlines():
        if line:
            rows.append(pipe_to_dict(line, fields))
    return rows


__all__ = [
    "FLOW_ROW_FIELDS",
    "DeploymentFlowGetRequest",
    "DeploymentFlowGetResponse",
    "DeploymentFlowStagesRequest",
    "DeploymentFlowStagesResponse",
    "DeploymentRunGetRequest",
    "DeploymentRunGetResponse",
    "DeploymentRunListRequest",
    "DeploymentRunListResponse",
    "DeploymentRunUpdateRequest",
    "DeploymentRunUpdateResponse",
    "DeploymentRunResolveTargetEnvRequest",
    "DeploymentRunResolveTargetEnvResponse",
    "error",
    "require_global",
    "run_id",
    "flow_id",
    "pipe_to_dict",
    "pipe_rows",
]
