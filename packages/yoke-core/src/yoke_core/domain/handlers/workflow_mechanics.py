"""Registered reads and bounded writes for Workflows mechanics editors."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_core.domain.approval_policy import (
    DEFAULT_APPROVAL_MODE,
    parse_approval_policy,
)


class MechanicsGetRequest(BaseModel):
    pass


class MechanicsGetResponse(BaseModel):
    testing_defaults: List[Dict[str, Any]]
    delivery_defaults: List[Dict[str, Any]]
    approvers: List[Dict[str, Any]]


class ProjectDefaultSetRequest(BaseModel):
    project: str = Field(..., min_length=1)
    workflow_id: str = Field(..., min_length=1)
    apply_to_all: bool = False


class TestingDefaultSetRequest(ProjectDefaultSetRequest):
    plan_id: int = Field(..., gt=0)


class DeliveryDefaultSetRequest(ProjectDefaultSetRequest):
    flow_id: str = Field(..., min_length=1)


class ApprovalAddress(BaseModel):
    """One transition's approval policy, validated by its single parser."""

    roles: List[str] = Field(default_factory=list)
    actors: List[int] = Field(default_factory=list)
    mode: str = DEFAULT_APPROVAL_MODE

    @model_validator(mode="after")
    def valid_approval_policy(self) -> "ApprovalAddress":
        parse_approval_policy(self.model_dump(), path="approval_defaults entry")
        return self


class ApprovalDefaultsPublishRequest(BaseModel):
    workflow_id: str = Field(..., min_length=1)
    expected_current_version: int = Field(..., gt=0)
    approval_defaults: Dict[str, ApprovalAddress]


class MutationResponse(BaseModel):
    result: Dict[str, Any]


def _error(code: str, message: str, jsonpath: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath=jsonpath),
    )


def _payload(
    request: FunctionCallRequest, model: type[BaseModel],
) -> tuple[Optional[BaseModel], Optional[HandlerOutcome]]:
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


def _actor_id(request: FunctionCallRequest) -> Optional[int]:
    from yoke_core.domain.actor_project_visibility import numeric_actor_id

    return numeric_actor_id(request.actor.actor_id if request.actor else None)


def handle_mechanics_get(request: FunctionCallRequest) -> HandlerOutcome:
    _, error = _payload(request, MechanicsGetRequest)
    if error is not None:
        return error
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.workflow_project_defaults import (
        list_approval_actors,
        list_delivery_defaults,
        list_testing_defaults,
    )

    with connect() as conn:
        result = {
            "testing_defaults": list_testing_defaults(conn),
            "delivery_defaults": list_delivery_defaults(conn),
            "approvers": list_approval_actors(conn),
        }
    return HandlerOutcome(result_payload=result, primary_success=True)


def handle_testing_default_set(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    payload, error = _payload(request, TestingDefaultSetRequest)
    if error is not None:
        return error
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.workflow_project_defaults import (
        WorkflowProjectDefaultError,
        set_testing_default,
    )

    try:
        with connect() as conn:
            result = set_testing_default(
                conn,
                actor_id=_actor_id(request),
                **payload.model_dump(),
            )
    except (LookupError, WorkflowProjectDefaultError) as exc:
        return _error("incompatible", str(exc), "$.payload")
    return HandlerOutcome(
        result_payload={"result": result}, primary_success=True,
    )


def handle_delivery_default_set(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    payload, error = _payload(request, DeliveryDefaultSetRequest)
    if error is not None:
        return error
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.workflow_project_defaults import (
        WorkflowProjectDefaultError,
        set_delivery_default,
    )

    try:
        with connect() as conn:
            result = set_delivery_default(conn, **payload.model_dump())
    except (LookupError, WorkflowProjectDefaultError) as exc:
        return _error("incompatible", str(exc), "$.payload")
    return HandlerOutcome(
        result_payload={"result": result}, primary_success=True,
    )


def handle_approval_defaults_publish(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    payload, error = _payload(request, ApprovalDefaultsPublishRequest)
    if error is not None:
        return error
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.workflow_definition_codec import WorkflowRegistryError
    from yoke_core.domain.workflow_policy_defaults import (
        publish_workflow_policy_defaults,
    )

    try:
        with connect() as conn:
            data = payload.model_dump()
            result = publish_workflow_policy_defaults(
                conn,
                published_by_actor_id=_actor_id(request),
                **data,
            )
    except (ValueError, WorkflowRegistryError) as exc:
        return _error("incompatible", str(exc), "$.payload")
    return HandlerOutcome(
        result_payload={"result": result}, primary_success=True,
    )


__all__ = [
    "ApprovalDefaultsPublishRequest",
    "DeliveryDefaultSetRequest",
    "MechanicsGetRequest",
    "MechanicsGetResponse",
    "MutationResponse",
    "TestingDefaultSetRequest",
    "handle_approval_defaults_publish",
    "handle_delivery_default_set",
    "handle_mechanics_get",
    "handle_testing_default_set",
]
