"""Deployment flow read handlers."""

from __future__ import annotations

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    HandlerOutcome,
)

from yoke_core.domain.handlers.deployment_common import (
    FLOW_ROW_FIELDS,
    error,
    flow_id,
    pipe_to_dict,
    require_global,
)


def handle_deployment_flow_get(request: FunctionCallRequest) -> HandlerOutcome:
    invalid = require_global(request, "deployment_flows.get")
    if invalid is not None:
        return invalid
    payload = request.payload or {}
    resolved_flow_id = flow_id(payload, "deployment_flows.get")
    if isinstance(resolved_flow_id, HandlerOutcome):
        return resolved_flow_id
    field = payload.get("field")
    if field is not None and not isinstance(field, str):
        return error(
            "payload_invalid", "field must be a string when present",
            jsonpath="$.payload.field",
        )

    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.flow import cmd_get

    conn = connect()
    try:
        try:
            raw = cmd_get(conn, resolved_flow_id, field)
        except LookupError as exc:
            return error(
                "not_found", str(exc), jsonpath="$.payload.flow_id",
            )
        except ValueError as exc:
            return error(
                "invalid_field", str(exc), jsonpath="$.payload.field",
            )
    finally:
        conn.close()

    if field:
        return HandlerOutcome(
            result_payload={
                "flow_id": resolved_flow_id,
                "field": field,
                "value": raw,
            },
            primary_success=True,
        )
    return HandlerOutcome(
        result_payload={
            "flow_id": resolved_flow_id,
            "fields": list(FLOW_ROW_FIELDS),
            "flow": pipe_to_dict(raw, FLOW_ROW_FIELDS),
        },
        primary_success=True,
    )


def handle_deployment_flow_stages(request: FunctionCallRequest) -> HandlerOutcome:
    invalid = require_global(request, "deployment_flows.stages")
    if invalid is not None:
        return invalid
    payload = request.payload or {}
    resolved_flow_id = flow_id(payload, "deployment_flows.stages")
    if isinstance(resolved_flow_id, HandlerOutcome):
        return resolved_flow_id

    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.flow import cmd_stages

    conn = connect()
    try:
        try:
            stages = cmd_stages(conn, resolved_flow_id)
        except LookupError as exc:
            return error(
                "not_found", str(exc), jsonpath="$.payload.flow_id",
            )
    finally:
        conn.close()
    return HandlerOutcome(
        result_payload={"flow_id": resolved_flow_id, "stages": stages},
        primary_success=True,
    )


def handle_deployment_flow_update_stages(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    invalid = require_global(request, "deployment_flows.update_stages")
    if invalid is not None:
        return invalid
    payload = request.payload or {}
    resolved_flow_id = flow_id(payload, "deployment_flows.update_stages")
    if isinstance(resolved_flow_id, HandlerOutcome):
        return resolved_flow_id
    stages = payload.get("stages")
    description = payload.get("description")
    if not isinstance(stages, str) or not stages.strip():
        return error(
            "payload_invalid", "stages must be a non-empty JSON string",
            jsonpath="$.payload.stages",
        )
    if description is not None and not isinstance(description, str):
        return error(
            "payload_invalid", "description must be a string when present",
            jsonpath="$.payload.description",
        )
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.flow_crud import cmd_update_stages

    conn = connect()
    try:
        try:
            message = cmd_update_stages(
                conn, resolved_flow_id, stages,
                description=description,
            )
        except LookupError as exc:
            return error("not_found", str(exc), jsonpath="$.payload.flow_id")
        except ValueError as exc:
            return error("definition_immutable", str(exc), jsonpath="$.payload")
    finally:
        conn.close()
    return HandlerOutcome(
        result_payload={"flow_id": resolved_flow_id, "message": message},
        primary_success=True,
    )


def handle_deployment_flow_describe(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    invalid = require_global(request, "deployment_flows.describe")
    if invalid is not None:
        return invalid
    payload = request.payload or {}
    resolved_flow_id = flow_id(payload, "deployment_flows.describe")
    if isinstance(resolved_flow_id, HandlerOutcome):
        return resolved_flow_id
    description = payload.get("description")
    if not isinstance(description, str) or not description.strip():
        return error(
            "payload_invalid", "description must be a non-empty string",
            jsonpath="$.payload.description",
        )
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.flow_crud import cmd_describe

    conn = connect()
    try:
        try:
            message = cmd_describe(conn, resolved_flow_id, description)
        except LookupError as exc:
            return error("not_found", str(exc), jsonpath="$.payload.flow_id")
    finally:
        conn.close()
    return HandlerOutcome(
        result_payload={"flow_id": resolved_flow_id, "message": message},
        primary_success=True,
    )


def handle_deployment_flow_set_status(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    invalid = require_global(request, "deployment_flows.set_status")
    if invalid is not None:
        return invalid
    payload = request.payload or {}
    resolved_flow_id = flow_id(payload, "deployment_flows.set_status")
    if isinstance(resolved_flow_id, HandlerOutcome):
        return resolved_flow_id
    status = payload.get("status")
    if not isinstance(status, str):
        return error(
            "payload_invalid", "status must be active or disabled",
            jsonpath="$.payload.status",
        )

    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.flow import cmd_set_status

    conn = connect()
    try:
        try:
            cmd_set_status(conn, resolved_flow_id, status)
        except LookupError as exc:
            return error(
                "not_found", str(exc), jsonpath="$.payload.flow_id",
            )
        except ValueError as exc:
            return error(
                "invalid_status", str(exc), jsonpath="$.payload.status",
            )
    finally:
        conn.close()
    return HandlerOutcome(
        result_payload={
            "flow_id": resolved_flow_id,
            "status": status.strip().lower(),
        },
        primary_success=True,
    )


def handle_deployment_flow_create(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    """Create one deployment flow for a project."""
    project = str(request.target.project_id or "").strip()
    if not project:
        return error(
            "target_invalid",
            "deployment_flows.create requires target.project_id",
            jsonpath="$.target.project_id",
        )
    payload = request.payload or {}
    resolved_flow_id = flow_id(payload, "deployment_flows.create")
    if isinstance(resolved_flow_id, HandlerOutcome):
        return resolved_flow_id
    name = payload.get("name")
    stages = payload.get("stages")
    if not isinstance(name, str) or not name.strip():
        return error(
            "payload_invalid", "name must be a non-empty string",
            jsonpath="$.payload.name",
        )
    if not isinstance(stages, str) or not stages.strip():
        return error(
            "payload_invalid", "stages must be a non-empty JSON string",
            jsonpath="$.payload.stages",
        )

    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.flow_create import cmd_create

    conn = connect()
    try:
        try:
            message = cmd_create(
                conn,
                resolved_flow_id,
                project,
                name,
                str(payload.get("description") or ""),
                stages,
                on_failure=str(payload.get("on_failure") or "halt"),
                target_tier=payload.get("target_tier"),
                environment=payload.get("environment"),
                done_description=payload.get("done_description"),
                status=str(payload.get("status") or "active"),
            )
        except LookupError as exc:
            return error("not_found", str(exc), jsonpath="$.payload")
        except ValueError as exc:
            return error("flow_invalid", str(exc), jsonpath="$.payload")
    finally:
        conn.close()
    return HandlerOutcome(
        result_payload={"flow_id": resolved_flow_id, "message": message},
        primary_success=True,
    )


__all__ = [
    "handle_deployment_flow_create",
    "handle_deployment_flow_describe",
    "handle_deployment_flow_get",
    "handle_deployment_flow_set_status",
    "handle_deployment_flow_stages",
    "handle_deployment_flow_update_stages",
]
