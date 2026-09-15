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
    #: Without ``item_ids`` this caps the whole recency page. With them it
    #: caps rows PER ITEM, so one busy subject cannot crowd another out of
    #: the answer, and ``item_selection`` reports what that cost.
    limit: int = Field(default=100, ge=1, le=500)
    deployment_run_id: Optional[str] = Field(default=None, min_length=1)
    #: Narrows to the QA these items own, so a reader showing a known set of
    #: subjects reads their evidence rather than whatever happens to be
    #: recent. Absent reads the project; an empty list matches nothing.
    item_ids: Optional[List[int]] = Field(default=None, max_length=200)
    #: The deployment runs a caller is drawing, so an item's answer is sized
    #: by what is on screen rather than by how many releases it has ever been
    #: part of. An item's run-less checks always travel. Absent reads every
    #: run group; an empty list reads only the run-less ones.
    deployment_run_ids: Optional[List[str]] = Field(default=None, max_length=200)


class RowsResponse(BaseModel):
    rows: List[Dict[str, Any]]


class ActivitySummaryResponse(BaseModel):
    day: str
    total: int = Field(..., ge=0)
    counts: Dict[str, int]


class ActivityTruncatedGroup(BaseModel):
    """One item's checks within one run group, reported as cut short."""

    item_id: int
    deployment_run_id: Optional[str] = None


class ActivityItemSelection(BaseModel):
    """How an item-scoped read was bounded, and which groups it cut short."""

    per_group_limit: int = Field(..., ge=1)
    truncated_groups: List[ActivityTruncatedGroup]


class ActivityListResponse(RowsResponse):
    summary: ActivitySummaryResponse
    #: Present only for an ``item_ids`` read, whose bounding is per item.
    item_selection: Optional[ActivityItemSelection] = None


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
                item_ids=payload.item_ids,
                deployment_run_ids=payload.deployment_run_ids,
                limit=payload.limit,
            )
    except LookupError as exc:
        return _error("not_found", str(exc), "$.payload.project")
    return HandlerOutcome(result_payload=result, primary_success=True)


__all__ = [
    "ActivityItemSelection",
    "ActivityTruncatedGroup",
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
