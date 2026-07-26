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


class WorkflowCurrentSetResponse(BaseModel):
    workflow_id: str
    version: int
    version_id: int


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
            )
    except WorkflowRegistryError as exc:
        return _error("incompatible", str(exc), "$.payload.version")
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
    "WorkflowItemGetRequest",
    "WorkflowItemMigrateRequest",
    "WorkflowItemMigrateResponse",
    "WorkflowItemPinResponse",
    "handle_workflows_current_set",
    "handle_workflows_item_get",
    "handle_workflows_item_migrate",
]
