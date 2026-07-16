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


__all__ = [
    "handle_deployment_flow_get",
    "handle_deployment_flow_set_status",
    "handle_deployment_flow_stages",
]
