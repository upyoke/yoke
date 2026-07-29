"""Registered read handlers for QA methods, plans, and activity."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class ProjectReadRequest(BaseModel):
    project: str = Field(..., min_length=1)


class MethodGetRequest(ProjectReadRequest):
    method_id: str = Field(..., min_length=1)


class PlanGetRequest(ProjectReadRequest):
    plan_id: int
    deployment_run_id: Optional[str] = Field(default=None, min_length=1)


class ActivityListRequest(ProjectReadRequest):
    limit: int = Field(default=100, ge=1, le=500)
    deployment_run_id: Optional[str] = Field(default=None, min_length=1)


class RowsResponse(BaseModel):
    rows: List[Dict[str, Any]]


class ActivitySummaryResponse(BaseModel):
    day: str
    total: int = Field(..., ge=0)
    counts: Dict[str, int]


class ActivityListResponse(RowsResponse):
    summary: ActivitySummaryResponse


class MethodGetResponse(BaseModel):
    method: Dict[str, Any]


class PlanGetResponse(BaseModel):
    plan: Dict[str, Any]


def _error(code: str, message: str, jsonpath: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath=jsonpath),
    )


def _payload(
    request: FunctionCallRequest,
    model: type[BaseModel],
) -> tuple[BaseModel | None, HandlerOutcome | None]:
    if request.target.kind != "global":
        return None, _error(
            "target_invalid",
            f"{request.function} requires target.kind='global'",
            "$.target.kind",
        )
    try:
        return model.model_validate(request.payload or {}), None
    except ValueError as exc:
        return None, _error("payload_invalid", str(exc), "$.payload")


def handle_method_list(request: FunctionCallRequest) -> HandlerOutcome:
    payload, error = _payload(request, ProjectReadRequest)
    if error is not None:
        return error
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.qa_catalog_reads import list_methods

    try:
        with connect() as conn:
            rows = list_methods(conn, project=payload.project)
    except LookupError as exc:
        return _error("not_found", str(exc), "$.payload.project")
    return HandlerOutcome(result_payload={"rows": rows}, primary_success=True)


def handle_method_get(request: FunctionCallRequest) -> HandlerOutcome:
    payload, error = _payload(request, MethodGetRequest)
    if error is not None:
        return error
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.qa_catalog_reads import get_method

    try:
        with connect() as conn:
            method = get_method(
                conn,
                method_id=payload.method_id,
                project=payload.project,
            )
    except LookupError as exc:
        return _error("not_found", str(exc), "$.payload.method_id")
    return HandlerOutcome(
        result_payload={"method": method},
        primary_success=True,
    )


def handle_plan_list(request: FunctionCallRequest) -> HandlerOutcome:
    payload, error = _payload(request, ProjectReadRequest)
    if error is not None:
        return error
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.qa_catalog_reads import list_plans

    try:
        with connect() as conn:
            rows = list_plans(conn, project=payload.project)
    except LookupError as exc:
        return _error("not_found", str(exc), "$.payload.project")
    return HandlerOutcome(result_payload={"rows": rows}, primary_success=True)


def handle_plan_get(request: FunctionCallRequest) -> HandlerOutcome:
    payload, error = _payload(request, PlanGetRequest)
    if error is not None:
        return error
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.qa_plan_detail import get_plan

    try:
        with connect() as conn:
            plan = get_plan(
                conn,
                plan_id=payload.plan_id,
                deployment_run_id=payload.deployment_run_id,
            )
    except LookupError as exc:
        return _error("not_found", str(exc), "$.payload.plan_id")
    project_refs = {str(plan["project"])}
    if plan.get("project_id") is not None:
        project_refs.add(str(plan["project_id"]))
    if str(payload.project) not in project_refs:
        return _error("not_found", "QA plan not found", "$.payload.plan_id")
    return HandlerOutcome(result_payload={"plan": plan}, primary_success=True)


def handle_activity_list(request: FunctionCallRequest) -> HandlerOutcome:
    payload, error = _payload(request, ActivityListRequest)
    if error is not None:
        return error
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.qa_catalog_reads import read_activity

    try:
        with connect() as conn:
            result = read_activity(
                conn,
                project=payload.project,
                deployment_run_id=payload.deployment_run_id,
                limit=payload.limit,
            )
    except LookupError as exc:
        return _error("not_found", str(exc), "$.payload.project")
    return HandlerOutcome(result_payload=result, primary_success=True)


__all__ = [
    "ActivityListResponse",
    "ActivityListRequest",
    "ActivitySummaryResponse",
    "MethodGetRequest",
    "MethodGetResponse",
    "PlanGetRequest",
    "PlanGetResponse",
    "ProjectReadRequest",
    "RowsResponse",
    "handle_activity_list",
    "handle_method_get",
    "handle_method_list",
    "handle_plan_get",
    "handle_plan_list",
]
