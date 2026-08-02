"""Registered management handlers for authoring and attaching QA plans."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_core.domain.handlers.qa_plan_materialize import (
    MaterializeRequest,
    RematerializeRequest,
    handle_materialize,
    handle_rematerialize,
)


class PlanCreateRequest(BaseModel):
    project: str = Field(..., min_length=1)
    slug: str = Field(..., min_length=1)
    name: Optional[str] = None
    description: str = ""
    success_policy_id: str = "all-pass"
    success_policy_params: Dict[str, Any] = Field(default_factory=dict)
    target_environment_id: str = Field(..., min_length=1)


class PlanCreateResponse(BaseModel):
    id: int
    project_id: int
    project: str
    slug: str
    name: str


class ProjectMethodRegisterRequest(BaseModel):
    project: str = Field(..., min_length=1)
    slug: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)
    executor_id: str = Field(..., min_length=1)
    verdict_path: str = Field(..., min_length=1)
    verdict_contract: str = Field(..., min_length=1)
    evidence_contract: str = Field(..., min_length=1)
    concurrency_mode: str = "parallel"
    success_policy_params: Dict[str, Any] = Field(default_factory=dict)


class ProjectMethodRegisterResponse(BaseModel):
    id: str
    project: str
    project_id: int
    executor_id: str
    verdict_path: str


class PlanCasesReplaceRequest(BaseModel):
    project: str = Field(..., min_length=1)
    plan_id: int
    cases: List[Dict[str, Any]]


class PlanCasesReplaceResponse(BaseModel):
    plan_id: int
    case_count: int


class ProjectDefaultSetRequest(BaseModel):
    project: str = Field(..., min_length=1)
    plan_id: int
    workflow_id: str = Field(..., min_length=1)
    transition_id: str = Field(..., min_length=1)
    qa_phase: str = "verification"


class ItemAttachRequest(BaseModel):
    project: str = Field(..., min_length=1)
    plan_id: int
    transition_id: str = Field(..., min_length=1)
    qa_phase: str = "verification"


class MutationResponse(BaseModel):
    result: Dict[str, Any]


def _error(code: str, message: str, jsonpath: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath=jsonpath),
    )


def _payload(
    request: FunctionCallRequest,
    model: type[BaseModel],
    *,
    target_kind: str,
) -> tuple[BaseModel | None, HandlerOutcome | None]:
    if request.target.kind != target_kind:
        return None, _error(
            "target_invalid",
            f"{request.function} requires target.kind={target_kind!r}",
            "$.target.kind",
        )
    try:
        return model.model_validate(request.payload or {}), None
    except ValueError as exc:
        return None, _error("payload_invalid", str(exc), "$.payload")


def _actor_id(request: FunctionCallRequest) -> Optional[int]:
    from yoke_core.domain.actor_project_visibility import numeric_actor_id

    return numeric_actor_id(request.actor.actor_id if request.actor else None)


def _project_matches(conn: Any, *, plan_id: int, project: str) -> None:
    from yoke_core.domain.project_identity import resolve_project
    from yoke_core.domain.qa_plan_management import QaPlanError, _plan_row

    identity = resolve_project(conn, project, required=False)
    if identity is None:
        raise QaPlanError(f"project {project!r} not found")
    plan = _plan_row(conn, plan_id)
    if int(plan["project_id"]) != int(identity.id):
        raise QaPlanError("QA plan not found in the requested project")


def handle_plan_create(request: FunctionCallRequest) -> HandlerOutcome:
    payload, error = _payload(
        request,
        PlanCreateRequest,
        target_kind="global",
    )
    if error is not None:
        return error
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.qa_plan_management import QaPlanError, create_plan

    try:
        with connect() as conn:
            result = create_plan(conn, **payload.model_dump())
    except QaPlanError as exc:
        return _error("incompatible", str(exc), "$.payload")
    return HandlerOutcome(result_payload=result, primary_success=True)


def handle_project_method_register(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    payload, error = _payload(
        request,
        ProjectMethodRegisterRequest,
        target_kind="global",
    )
    if error is not None:
        return error
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.qa_method_management import (
        QaMethodError,
        register_project_method,
    )

    try:
        with connect() as conn:
            result = register_project_method(conn, **payload.model_dump())
    except QaMethodError as exc:
        return _error("incompatible", str(exc), "$.payload")
    return HandlerOutcome(result_payload=result, primary_success=True)


def handle_plan_cases_replace(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    payload, error = _payload(
        request,
        PlanCasesReplaceRequest,
        target_kind="global",
    )
    if error is not None:
        return error
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.qa_plan_management import (
        QaPlanError,
        replace_plan_cases,
    )

    try:
        with connect() as conn:
            _project_matches(
                conn,
                plan_id=payload.plan_id,
                project=payload.project,
            )
            result = replace_plan_cases(
                conn,
                plan_id=payload.plan_id,
                cases=payload.cases,
            )
    except QaPlanError as exc:
        return _error("incompatible", str(exc), "$.payload")
    return HandlerOutcome(result_payload=result, primary_success=True)


def handle_project_default_set(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    payload, error = _payload(
        request,
        ProjectDefaultSetRequest,
        target_kind="global",
    )
    if error is not None:
        return error
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.qa_plan_attachments import set_project_default
    from yoke_core.domain.qa_plan_management import QaPlanError

    try:
        with connect() as conn:
            _project_matches(
                conn,
                plan_id=payload.plan_id,
                project=payload.project,
            )
            data = payload.model_dump(exclude={"project"})
            result = set_project_default(
                conn,
                actor_id=_actor_id(request),
                **data,
            )
    except QaPlanError as exc:
        return _error("incompatible", str(exc), "$.payload")
    return HandlerOutcome(result_payload={"result": result}, primary_success=True)


def handle_item_attach(request: FunctionCallRequest) -> HandlerOutcome:
    payload, error = _payload(
        request,
        ItemAttachRequest,
        target_kind="item",
    )
    if error is not None:
        return error
    item_id = request.target.item_id
    if item_id is None:
        return _error("target_invalid", "item id is required", "$.target")
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.qa_plan_attachments import attach_plan_to_item
    from yoke_core.domain.qa_plan_management import QaPlanError

    try:
        with connect() as conn:
            _project_matches(
                conn,
                plan_id=payload.plan_id,
                project=payload.project,
            )
            result = attach_plan_to_item(
                conn,
                item_id=int(item_id),
                plan_id=payload.plan_id,
                transition_id=payload.transition_id,
                qa_phase=payload.qa_phase,
                actor_id=_actor_id(request),
            )
    except QaPlanError as exc:
        return _error("incompatible", str(exc), "$.payload")
    return HandlerOutcome(result_payload={"result": result}, primary_success=True)


__all__ = [
    "ItemAttachRequest",
    "MaterializeRequest",
    "RematerializeRequest",
    "MutationResponse",
    "PlanCasesReplaceRequest",
    "PlanCasesReplaceResponse",
    "PlanCreateRequest",
    "PlanCreateResponse",
    "ProjectMethodRegisterRequest",
    "ProjectMethodRegisterResponse",
    "ProjectDefaultSetRequest",
    "handle_item_attach",
    "handle_materialize",
    "handle_rematerialize",
    "handle_plan_cases_replace",
    "handle_plan_create",
    "handle_project_method_register",
    "handle_project_default_set",
]
