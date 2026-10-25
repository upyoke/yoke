"""Registered read handlers for QA methods, plans, and activity."""

from __future__ import annotations

from yoke_contracts.list_paging import ListPageRequest, ListPageResponse, page_result

from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_contracts.read_detail import DETAIL_FULL, DETAIL_SUMMARY, ReadDetail


class ProjectReadRequest(BaseModel):
    project: str = Field(..., min_length=1)


class MethodListRequest(ListPageRequest):
    project: Optional[str] = None


class MethodGetRequest(BaseModel):
    method_id: str = Field(..., min_length=1)
    project: Optional[str] = None
    detail: ReadDetail = DETAIL_SUMMARY


class PlanListRequest(ProjectReadRequest):
    limit: Optional[int] = Field(default=None, ge=1, le=500)
    offset: int = Field(default=0, ge=0)
    detail: ReadDetail = DETAIL_SUMMARY
    include_retired: bool = False


class PlanGetRequest(ProjectReadRequest):
    plan_id: int | str
    deployment_run_id: Optional[str] = Field(default=None, min_length=1)
    detail: ReadDetail = Field(
        default=DETAIL_SUMMARY,
        description=(
            "summary serves the cases, methods, target and verdicts; full "
            "adds each probe's source and every proof's evidence."
        ),
    )


class ActivityListRequest(ProjectReadRequest):
    detail: ReadDetail = DETAIL_SUMMARY
    limit: int = Field(default=100, ge=1, le=500)
    offset: int = Field(default=0, ge=0)
    deployment_run_id: Optional[str] = Field(default=None, min_length=1)
    item_ids: Optional[List[int]] = Field(default=None, max_length=200)
    deployment_run_ids: Optional[List[str]] = Field(default=None, max_length=200)


class RowsResponse(ListPageResponse):
    rows: List[Dict[str, Any]]


class ActivitySummaryResponse(BaseModel):
    day: str
    total: int = Field(..., ge=0)
    counts: Dict[str, int]


class ActivityTruncatedGroup(BaseModel):
    """One item's checks within one run group, reported as cut short."""

    item_id: int
    deployment_run_id: Optional[str] = None


class ActivityRunGroupSelection(BaseModel):
    """Run-group bounds and truncated groups."""

    per_group_limit: int = Field(..., ge=1)
    truncated_groups: List[ActivityTruncatedGroup]


class ActivityTotalSelection(BaseModel):
    """How an item read without run groups was capped, and what matched."""

    limit: int = Field(..., ge=1)
    total: int = Field(..., ge=0)
    truncated: bool


class ActivityListResponse(RowsResponse):
    summary: ActivitySummaryResponse
    item_selection: Optional[
        Union[ActivityRunGroupSelection, ActivityTotalSelection]
    ] = None
    run_sharing: Optional[Dict[str, Any]] = None


class MethodGetResponse(BaseModel):
    method: Dict[str, Any]


class PlanGetResponse(BaseModel):
    plan: Dict[str, Any]
    detail: ReadDetail = DETAIL_SUMMARY


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


_PROJECT_REQUIRED = (
    "project_required: this session has no project. Pass --project SLUG."
)


class MethodProjectError(Exception):
    """The method read has neither an explicit project nor a session project."""


def _method_project(
    conn: Any, request: FunctionCallRequest, explicit: Optional[str]
) -> str:
    chosen = str(explicit or "").strip()
    if chosen:
        return chosen
    from yoke_core.domain.sessions import SessionError
    from yoke_core.domain.sessions_identity_read import resolve_session_identity

    try:
        identity = resolve_session_identity(conn, request.actor.session_id)
    except SessionError as exc:
        raise MethodProjectError(str(exc)) from exc
    if identity.project_id is None:
        raise MethodProjectError(_PROJECT_REQUIRED)
    return str(identity.project_id)


def handle_method_list(request: FunctionCallRequest) -> HandlerOutcome:
    payload, error = _payload(request, MethodListRequest)
    if error is not None:
        return error
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.qa_catalog_reads import list_methods

    try:
        with connect() as conn:
            project = _method_project(conn, request, payload.project)
            rows = list_methods(conn, project=project)
    except MethodProjectError as exc:
        return _error("payload_invalid", str(exc), "$.payload.project")
    except LookupError as exc:
        return _error("not_found", str(exc), "$.payload.project")
    return HandlerOutcome(
        result_payload=page_result({"rows": rows}, "rows", request.payload or {}),
        primary_success=True,
    )


def handle_method_get(request: FunctionCallRequest) -> HandlerOutcome:
    payload, error = _payload(request, MethodGetRequest)
    if error is not None:
        return error
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.qa_catalog_reads import get_method

    try:
        with connect() as conn:
            project = _method_project(conn, request, payload.project)
            method = get_method(
                conn,
                method_id=payload.method_id,
                project=project,
                full=payload.detail == DETAIL_FULL,
            )
    except MethodProjectError as exc:
        return _error("payload_invalid", str(exc), "$.payload.project")
    except LookupError as exc:
        return _error("not_found", str(exc), "$.payload.method_id")
    return HandlerOutcome(
        result_payload={"method": method},
        primary_success=True,
    )


def handle_plan_list(request: FunctionCallRequest) -> HandlerOutcome:
    payload, error = _payload(request, PlanListRequest)
    if error is not None:
        return error
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.qa_catalog_reads import list_plans

    try:
        with connect() as conn:
            rows = list_plans(
                conn,
                project=payload.project,
                limit=payload.limit,
                offset=payload.offset,
                full=payload.detail == DETAIL_FULL,
                include_retired=payload.include_retired,
            )
    except LookupError as exc:
        return _error("not_found", str(exc), "$.payload.project")
    from yoke_core.domain.qa_plan_list_reads import DEFAULT_PLAN_LIMIT

    limit = payload.limit or DEFAULT_PLAN_LIMIT
    return HandlerOutcome(
        result_payload={
            "rows": rows,
            "limit": limit,
            "offset": payload.offset,
            "next_offset": payload.offset + len(rows) if len(rows) == limit else None,
            "detail": payload.detail,
            "detail_read": "yoke qa plan list --project P --full",
        },
        primary_success=True,
    )


def handle_plan_get(request: FunctionCallRequest) -> HandlerOutcome:
    payload, error = _payload(request, PlanGetRequest)
    if error is not None:
        return error
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.qa_plan_detail import get_plan

    try:
        with connect() as conn:
            plan_ref = str(payload.plan_id)
            if not plan_ref.isdecimal():
                from yoke_core.domain.project_identity import resolve_project_id
                from yoke_core.domain.db_helpers import query_one
                from yoke_core.domain import db_backend

                project_id = resolve_project_id(conn, payload.project)
                marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
                row = query_one(
                    conn,
                    f"SELECT id FROM qa_plans WHERE project_id={marker} AND slug={marker}",
                    (project_id, plan_ref),
                )
                if row is None:
                    raise LookupError(
                        f"QA plan {plan_ref!r} not found in project {payload.project}"
                    )
                plan_ref = str(row["id"])
            plan = get_plan(
                conn,
                plan_id=int(plan_ref),
                deployment_run_id=payload.deployment_run_id,
            )
    except LookupError as exc:
        return _error("not_found", str(exc), "$.payload.plan_id")
    project_refs = {str(plan["project"])}
    if plan.get("project_id") is not None:
        project_refs.add(str(plan["project_id"]))
    if str(payload.project) not in project_refs:
        return _error("not_found", "QA plan not found", "$.payload.plan_id")
    if payload.detail != DETAIL_FULL:
        from yoke_core.domain.qa_plan_summary import plan_summary

        plan = plan_summary(plan, project=str(payload.project))
    return HandlerOutcome(
        result_payload={"plan": plan, "detail": payload.detail},
        primary_success=True,
    )


def handle_activity_list(request: FunctionCallRequest) -> HandlerOutcome:
    payload, error = _payload(request, ActivityListRequest)
    if error is not None:
        return error
    if payload.offset and payload.deployment_run_ids is not None:
        return _error(
            "activity_group_offset_unsupported",
            "Per-run group reads cannot use offsets; omit offset or read one deployment_run_id.",
            "$.payload.offset",
        )
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
                offset=payload.offset,
            )
    except LookupError as exc:
        return _error("not_found", str(exc), "$.payload.project")
    result.update(
        limit=payload.limit,
        offset=payload.offset,
        next_offset=payload.offset + len(result["rows"])
        if len(result["rows"]) == payload.limit
        else None,
    )
    if payload.detail != DETAIL_FULL:
        for row in result["rows"]:
            for key in ("instructions", "artifacts", "execution_target_json"):
                row.pop(key, None)
    return HandlerOutcome(result_payload=result, primary_success=True)


__all__ = [
    "ActivityRunGroupSelection",
    "ActivityTotalSelection",
    "ActivityTruncatedGroup",
    "ActivityListResponse",
    "ActivityListRequest",
    "ActivitySummaryResponse",
    "MethodGetRequest",
    "MethodListRequest",
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
