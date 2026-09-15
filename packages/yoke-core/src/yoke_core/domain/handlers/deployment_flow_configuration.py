"""Registered whole-definition deployment-flow configuration handlers."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_core.domain.handlers.deployment_common import error, flow_id, require_global


class DeploymentFlowUpdateRequest(BaseModel):
    flow_id: str
    changes: Dict[str, Any] = Field(default_factory=dict)


class DeploymentFlowUpdateResponse(BaseModel):
    flow_id: str
    flow: Dict[str, Any]


class DeploymentFlowReorderRequest(BaseModel):
    flow_id: str
    order: List[str]


class DeploymentFlowReorderResponse(DeploymentFlowUpdateResponse):
    pass


class DeploymentFlowValidateRequest(BaseModel):
    project: str
    stages: str
    target_tier: Optional[str] = None
    environment: Optional[str] = None
    status: str = "disabled"


class DeploymentFlowValidateResponse(BaseModel):
    project: str
    valid: bool
    definition_schema_version: int
    execution_supported: bool
    unsupported_target_kinds: list[str] = Field(default_factory=list)
    serving_schema_version: int


class DeploymentFlowVersionRequest(BaseModel):
    source_flow_id: str
    new_flow_id: str
    name: str
    changes: Dict[str, Any] = Field(default_factory=dict)
    status: str = "disabled"


class DeploymentFlowVersionResponse(DeploymentFlowUpdateResponse):
    source_flow_id: str


def _clean_changes(raw: Any) -> dict[str, Any] | HandlerOutcome:
    if not isinstance(raw, dict):
        return error(
            "payload_invalid", "changes must be an object", jsonpath="$.payload.changes"
        )
    from yoke_core.domain.deployment_flow_versioning import CONFIG_FIELDS

    unknown = set(raw) - CONFIG_FIELDS
    if unknown:
        return error(
            "payload_invalid",
            f"changes has unknown fields: {sorted(unknown)}",
            jsonpath="$.payload.changes",
        )
    return dict(raw)


def handle_deployment_flow_update(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    invalid = require_global(request, "deployment_flows.update")
    if invalid is not None:
        return invalid
    payload = request.payload or {}
    resolved = flow_id(payload, "deployment_flows.update")
    if isinstance(resolved, HandlerOutcome):
        return resolved
    changes = _clean_changes(payload.get("changes"))
    if isinstance(changes, HandlerOutcome):
        return changes
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.deployment_flow_versioning import cmd_update_definition

    conn = connect()
    try:
        try:
            result = cmd_update_definition(conn, resolved, changes)
        except LookupError as exc:
            return error("not_found", str(exc), jsonpath="$.payload.flow_id")
        except ValueError as exc:
            return error("definition_update_rejected", str(exc), jsonpath="$.payload")
    finally:
        conn.close()
    return HandlerOutcome(
        result_payload={"flow_id": resolved, "flow": result},
        primary_success=True,
    )


def handle_deployment_flow_reorder(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    invalid = require_global(request, "deployment_flows.reorder")
    if invalid is not None:
        return invalid
    payload = request.payload or {}
    resolved = flow_id(payload, "deployment_flows.reorder")
    if isinstance(resolved, HandlerOutcome):
        return resolved
    order = payload.get("order")
    if not isinstance(order, list) or any(not isinstance(v, str) for v in order):
        return error(
            "payload_invalid",
            "order must be an array of stage names",
            jsonpath="$.payload.order",
        )
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.deployment_flow_versioning import cmd_reorder_stages

    conn = connect()
    try:
        try:
            result = cmd_reorder_stages(conn, resolved, order)
        except LookupError as exc:
            return error("not_found", str(exc), jsonpath="$.payload.flow_id")
        except ValueError as exc:
            return error("reorder_rejected", str(exc), jsonpath="$.payload.order")
    finally:
        conn.close()
    return HandlerOutcome(
        result_payload={"flow_id": resolved, "flow": result},
        primary_success=True,
    )


def handle_deployment_flow_validate(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    invalid = require_global(request, "deployment_flows.validate")
    if invalid is not None:
        return invalid
    payload = request.payload or {}
    project = payload.get("project") or request.target.project_id
    stages = payload.get("stages")
    if not isinstance(project, str) or not project.strip():
        return error(
            "payload_invalid", "project is required", jsonpath="$.payload.project"
        )
    if not isinstance(stages, str) or not stages.strip():
        return error(
            "payload_invalid", "stages is required", jsonpath="$.payload.stages"
        )
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.deployment_flow_versioning import cmd_validate_definition

    conn = connect()
    try:
        try:
            result = cmd_validate_definition(
                conn,
                project=project.strip(),
                stages=stages,
                target_tier=payload.get("target_tier"),
                environment=payload.get("environment"),
                status=str(payload.get("status") or "disabled"),
            )
        except (LookupError, ValueError) as exc:
            return error("definition_invalid", str(exc), jsonpath="$.payload")
    finally:
        conn.close()
    return HandlerOutcome(
        result_payload={"project": project.strip(), **result},
        primary_success=True,
    )


def handle_deployment_flow_version(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    invalid = require_global(request, "deployment_flows.version")
    if invalid is not None:
        return invalid
    payload = request.payload or {}
    source = payload.get("source_flow_id")
    new = payload.get("new_flow_id")
    name = payload.get("name")
    for key, value in (
        ("source_flow_id", source),
        ("new_flow_id", new),
        ("name", name),
    ):
        if not isinstance(value, str) or not value.strip():
            return error(
                "payload_invalid",
                f"{key} must be a non-empty string",
                jsonpath=f"$.payload.{key}",
            )
    changes = _clean_changes(payload.get("changes") or {})
    if isinstance(changes, HandlerOutcome):
        return changes
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.deployment_flow_versioning import cmd_version_definition

    conn = connect()
    try:
        try:
            result = cmd_version_definition(
                conn,
                source.strip(),
                new.strip(),
                name=name.strip(),
                changes=changes,
                status=str(payload.get("status") or "disabled"),
            )
        except LookupError as exc:
            return error("not_found", str(exc), jsonpath="$.payload.source_flow_id")
        except ValueError as exc:
            return error("version_rejected", str(exc), jsonpath="$.payload")
    finally:
        conn.close()
    return HandlerOutcome(
        result_payload={
            "source_flow_id": source.strip(),
            "flow_id": new.strip(),
            "flow": result,
        },
        primary_success=True,
    )


__all__ = [
    "DeploymentFlowReorderRequest",
    "DeploymentFlowReorderResponse",
    "DeploymentFlowUpdateRequest",
    "DeploymentFlowUpdateResponse",
    "DeploymentFlowValidateRequest",
    "DeploymentFlowValidateResponse",
    "DeploymentFlowVersionRequest",
    "DeploymentFlowVersionResponse",
    "handle_deployment_flow_reorder",
    "handle_deployment_flow_update",
    "handle_deployment_flow_validate",
    "handle_deployment_flow_version",
]
