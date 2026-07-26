"""Handlers for workflow version inspection, selection, and item migration."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class WorkflowItemGetRequest(BaseModel):
    pass


class WorkflowItemPinResponse(BaseModel):
    item_id: int
    workflow_id: str
    workflow_version: int
    workflow_version_id: int
    definition_digest: str
    status: str
    workflow_posture: Dict[str, Any]
    worktree_policy: str
    allowed_lane_roles: List[str]
    required_lane_roles: List[str]
    active_lanes: List[Dict[str, Any]]


class WorkflowCurrentSetRequest(BaseModel):
    workflow_id: str
    version: int
    expected_current_version: Optional[int] = None


class WorkflowCurrentSetResponse(BaseModel):
    workflow_id: str
    version: int
    version_id: int


class WorkflowVersionGetRequest(BaseModel):
    workflow_id: str
    version: int


class WorkflowVersionGetResponse(BaseModel):
    workflow_id: str
    version: int
    version_id: int
    definition_schema_version: int
    definition_digest: str
    published_at: str
    immutable_at: str
    published_by_actor_id: Optional[int] = None
    current: bool
    definition: Dict[str, Any]


class WorkflowPolicyDefaultsPublishRequest(BaseModel):
    workflow_id: str
    expected_current_version: int
    path_claims_default: bool


class WorkflowPolicyDefaultsPublishResponse(BaseModel):
    workflow_id: str
    version: int
    version_id: int
    definition_digest: str
    path_claims_default: bool


class WorkflowItemMigrateRequest(BaseModel):
    version: Optional[int] = None


class WorkflowItemMigrateResponse(BaseModel):
    changed: bool
    before: Dict[str, Any]
    after: Dict[str, Any]


def _error(code: str, message: str, jsonpath: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(
            code=code,
            message=message,
            jsonpath=jsonpath,
        ),
    )


def _item_id(request: FunctionCallRequest) -> Optional[int]:
    if request.target.kind != "item":
        return None
    return request.target.item_id


def handle_workflows_item_get(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    item_id = _item_id(request)
    if item_id is None:
        return _error(
            "target_invalid",
            "workflows.item.get requires a resolved item target",
            "$.target",
        )
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.workflow_item_versioning import (
        inspect_item_workflow_pin,
    )

    try:
        with connect() as conn:
            result = inspect_item_workflow_pin(conn, int(item_id))
    except (LookupError, ValueError, RuntimeError) as exc:
        return _error("not_found", str(exc), "$.target.item_id")
    return HandlerOutcome(result_payload=result, primary_success=True)


def handle_workflows_current_set(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    if request.target.kind != "global":
        return _error(
            "target_invalid",
            "workflows.current.set requires target.kind='global'",
            "$.target.kind",
        )
    try:
        payload = WorkflowCurrentSetRequest.model_validate(request.payload or {})
    except ValueError as exc:
        return _error("payload_invalid", str(exc), "$.payload")
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.workflow_registry import (
        WorkflowRegistryError,
        set_current_workflow_version,
    )

    try:
        with connect() as conn:
            result = set_current_workflow_version(
                conn,
                workflow_id=payload.workflow_id,
                version=payload.version,
                expected_current_version=payload.expected_current_version,
            )
    except WorkflowRegistryError as exc:
        return _error("incompatible", str(exc), "$.payload.version")
    return HandlerOutcome(result_payload=result, primary_success=True)


def handle_workflows_version_get(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    if request.target.kind != "global":
        return _error(
            "target_invalid",
            "workflows.version.get requires target.kind='global'",
            "$.target.kind",
        )
    try:
        payload = WorkflowVersionGetRequest.model_validate(request.payload or {})
    except ValueError as exc:
        return _error("payload_invalid", str(exc), "$.payload")
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.workflow_registry import (
        WorkflowRegistryError,
        get_workflow_version,
    )

    try:
        with connect() as conn:
            result = get_workflow_version(
                conn,
                workflow_id=payload.workflow_id,
                version=payload.version,
            )
    except WorkflowRegistryError as exc:
        return _error("not_found", str(exc), "$.payload.version")
    return HandlerOutcome(result_payload=result, primary_success=True)


def handle_workflows_policy_defaults_publish(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    if request.target.kind != "global":
        return _error(
            "target_invalid",
            "workflows.policy_defaults.publish requires target.kind='global'",
            "$.target.kind",
        )
    try:
        payload = WorkflowPolicyDefaultsPublishRequest.model_validate(
            request.payload or {}
        )
    except ValueError as exc:
        return _error("payload_invalid", str(exc), "$.payload")
    from yoke_core.domain.actor_project_visibility import numeric_actor_id
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.workflow_definition_codec import WorkflowRegistryError
    from yoke_core.domain.workflow_policy_defaults import (
        publish_workflow_policy_defaults,
    )

    actor_id = numeric_actor_id(
        request.actor.actor_id if request.actor else None
    )
    try:
        with connect() as conn:
            result = publish_workflow_policy_defaults(
                conn,
                workflow_id=payload.workflow_id,
                expected_current_version=payload.expected_current_version,
                path_claims_default=payload.path_claims_default,
                published_by_actor_id=actor_id,
            )
    except WorkflowRegistryError as exc:
        return _error("incompatible", str(exc), "$.payload")
    return HandlerOutcome(result_payload=result, primary_success=True)


def handle_workflows_item_migrate(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    item_id = _item_id(request)
    if item_id is None:
        return _error(
            "target_invalid",
            "workflows.item.migrate requires a resolved item target",
            "$.target",
        )
    try:
        payload = WorkflowItemMigrateRequest.model_validate(request.payload or {})
    except ValueError as exc:
        return _error("payload_invalid", str(exc), "$.payload")
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.workflow_definition_codec import (
        WorkflowRegistryError,
    )
    from yoke_core.domain.workflow_item_versioning import (
        migrate_item_workflow_pin,
    )

    try:
        with connect() as conn:
            result = migrate_item_workflow_pin(
                conn,
                item_id=int(item_id),
                target_version=payload.version,
            )
    except WorkflowRegistryError as exc:
        return _error("incompatible", str(exc), "$.payload.version")
    return HandlerOutcome(result_payload=result, primary_success=True)


__all__ = [
    "WorkflowCurrentSetRequest",
    "WorkflowCurrentSetResponse",
    "WorkflowPolicyDefaultsPublishRequest",
    "WorkflowPolicyDefaultsPublishResponse",
    "WorkflowItemGetRequest",
    "WorkflowItemMigrateRequest",
    "WorkflowItemMigrateResponse",
    "WorkflowItemPinResponse",
    "WorkflowVersionGetRequest",
    "WorkflowVersionGetResponse",
    "handle_workflows_current_set",
    "handle_workflows_item_get",
    "handle_workflows_item_migrate",
    "handle_workflows_policy_defaults_publish",
    "handle_workflows_version_get",
]
