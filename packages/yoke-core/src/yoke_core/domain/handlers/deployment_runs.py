"""Deployment run read/update handlers."""

from __future__ import annotations

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    HandlerOutcome,
)

from yoke_core.domain.handlers.deployment_common import (
    error,
    pipe_to_dict,
    require_global,
    run_id,
)
from yoke_core.domain.handlers.deployment_run_creation import (
    handle_deployment_run_create,
)


def handle_deployment_run_get(request: FunctionCallRequest) -> HandlerOutcome:
    resolved_run_id = run_id(request, "deployment_runs.get")
    if isinstance(resolved_run_id, HandlerOutcome):
        return resolved_run_id
    payload = request.payload or {}
    field = payload.get("field")
    if field is not None and not isinstance(field, str):
        return error(
            "payload_invalid",
            "field must be a string when present",
            jsonpath="$.payload.field",
        )

    from yoke_core.domain.deployment_runs_crud_query import cmd_get
    from yoke_core.domain.deployment_runs_schema import RUN_FIELDS

    try:
        raw = cmd_get(resolved_run_id, field=field)
    except ValueError as exc:
        return error("invalid_field", str(exc), jsonpath="$.payload.field")
    if raw is None:
        return error(
            "not_found",
            f"deployment run '{resolved_run_id}' not found",
            jsonpath="$.target.workflow_run_id",
        )
    if field:
        return HandlerOutcome(
            result_payload={
                "run_id": resolved_run_id,
                "field": field,
                "value": raw,
            },
            primary_success=True,
        )
    parsed = pipe_to_dict(raw, RUN_FIELDS)
    from yoke_core.domain.deployment_run_carried_work import parse_carried_work

    parsed["carried_work"] = parse_carried_work(parsed.get("carried_work"))
    return HandlerOutcome(
        result_payload={
            "run_id": resolved_run_id,
            "fields": list(RUN_FIELDS),
            "run": parsed,
        },
        primary_success=True,
    )


def handle_deployment_run_list(request: FunctionCallRequest) -> HandlerOutcome:
    invalid = require_global(request, "deployment_runs.list")
    if invalid is not None:
        return invalid
    payload = request.payload or {}
    project = payload.get("project")
    status = payload.get("status")
    limit = payload.get("limit")
    for key, value in (("project", project), ("status", status)):
        if value is not None and not isinstance(value, str):
            return error(
                "payload_invalid",
                f"{key} must be a string when present",
                jsonpath=f"$.payload.{key}",
            )
    if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int)):
        return error(
            "payload_invalid",
            "limit must be an integer when present",
            jsonpath="$.payload.limit",
        )

    from yoke_core.domain.deployment_runs_crud_query import (
        DEFAULT_RUN_LIST_LIMIT,
        MAX_RUN_LIST_LIMIT,
    )
    from yoke_core.domain.deployment_run_list_read import (
        RUN_PRESENTATION_FIELDS,
        list_deployment_runs,
    )
    from yoke_core.domain.deployment_runs_schema import RUN_FIELDS

    resolved_limit = DEFAULT_RUN_LIST_LIMIT if limit is None else limit
    if resolved_limit < 1 or resolved_limit > MAX_RUN_LIST_LIMIT:
        return error(
            "payload_invalid",
            f"limit must be from 1 to {MAX_RUN_LIST_LIMIT}",
            jsonpath="$.payload.limit",
        )
    rows = list_deployment_runs(
        project=project,
        status=status,
        limit=resolved_limit,
    )
    return HandlerOutcome(
        result_payload={
            "fields": [*RUN_FIELDS, *RUN_PRESENTATION_FIELDS],
            "rows": rows,
            "limit": resolved_limit,
        },
        primary_success=True,
    )


def handle_deployment_run_update(request: FunctionCallRequest) -> HandlerOutcome:
    resolved_run_id = run_id(request, "deployment_runs.update")
    if isinstance(resolved_run_id, HandlerOutcome):
        return resolved_run_id
    payload = request.payload or {}
    field = payload.get("field")
    value = payload.get("value")
    force = bool(payload.get("force", False))
    if not isinstance(field, str) or not field.strip():
        return error(
            "payload_invalid",
            "field is required",
            jsonpath="$.payload.field",
        )
    if value is None:
        return error(
            "payload_invalid",
            "value is required",
            jsonpath="$.payload.value",
        )

    from yoke_core.domain.deployment_runs_crud_mutate import cmd_update

    err = cmd_update(resolved_run_id, field.strip(), str(value), force=force)
    if err:
        lower = err.lower()
        if "not found" in lower:
            return error(
                "not_found",
                err,
                jsonpath="$.target.workflow_run_id",
            )
        if "not updatable" in lower:
            return error("invalid_field", err, jsonpath="$.payload.field")
        if "invalid status" in lower:
            return error("payload_invalid", err, jsonpath="$.payload.value")
        return error("update_failed", err)
    return HandlerOutcome(
        result_payload={
            "run_id": resolved_run_id,
            "field": field.strip(),
            "value": str(value),
            "updated": True,
        },
        primary_success=True,
    )


def handle_deployment_run_approve(request: FunctionCallRequest) -> HandlerOutcome:
    """Approve the exact run's current Yoke-owned approval stage."""
    resolved_run_id = run_id(request, "deployment_runs.approve")
    if isinstance(resolved_run_id, HandlerOutcome):
        return resolved_run_id
    payload = request.payload or {}
    note = payload.get("note")
    if note is not None and (not isinstance(note, str) or len(note) > 2000):
        return error(
            "payload_invalid",
            "note must be a string of at most 2000 characters when present",
            jsonpath="$.payload.note",
        )

    from yoke_core.domain.deployment_run_approval import (
        RunApprovalRejected,
        approve_run,
        emit_run_approval,
    )

    try:
        actor_id = request.actor.actor_id
        if actor_id is None or not str(actor_id).isdigit():
            return error("permission_denied", "a numeric actor_id is required")
        approval = approve_run(
            resolved_run_id,
            actor_id=int(actor_id),
            session_id=request.actor.session_id,
            note=note,
        )
    except LookupError as exc:
        return error("not_found", str(exc), jsonpath="$.target.workflow_run_id")
    except PermissionError as exc:
        return error("permission_denied", str(exc))
    except RunApprovalRejected as exc:
        return error("invalid_state", str(exc))
    event_id = emit_run_approval(
        approval,
        actor_id=request.actor.actor_id,
        session_id=request.actor.session_id,
        note=note,
    )
    return HandlerOutcome(
        result_payload={
            "run_id": approval.run_id,
            "project": approval.project,
            "approved_stage": approval.approved_stage,
            "next_stage": approval.next_stage,
            "approved_at": approval.approved_at,
            "approver_actor_id": request.actor.actor_id,
            "approver_session_id": request.actor.session_id,
            "note": note,
            "member_item_ids": list(approval.member_item_ids),
            "decision_request_id": approval.decision_request_id,
            "event_id": event_id,
        },
        primary_success=True,
    )


def handle_deployment_run_resolve_target(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    invalid = require_global(request, "deployment_runs.resolve_target")
    if invalid is not None:
        return invalid
    payload = request.payload or {}
    project = payload.get("project")
    flow = payload.get("flow")
    environment = payload.get("environment")
    if not isinstance(project, str) or not project.strip():
        return error(
            "payload_invalid",
            "project is required",
            jsonpath="$.payload.project",
        )
    if not isinstance(flow, str) or not flow.strip():
        return error(
            "payload_invalid",
            "flow is required",
            jsonpath="$.payload.flow",
        )
    if environment is not None and not isinstance(environment, str):
        return error(
            "payload_invalid",
            "environment must be a string when present",
            jsonpath="$.payload.environment",
        )

    from yoke_core.domain.deployment_run_target_resolution import (
        EnvironmentRegistryMigrationRequired,
        cmd_resolve_target,
    )

    try:
        tier, _environment_id, environment_name = cmd_resolve_target(
            project.strip(),
            flow.strip(),
            environment_override=environment,
        )
    except EnvironmentRegistryMigrationRequired as exc:
        return error(exc.code, str(exc))
    except LookupError as exc:
        return error("not_found", str(exc))
    except ValueError as exc:
        return error("payload_invalid", str(exc))
    return HandlerOutcome(
        result_payload={
            "project": project.strip(),
            "flow": flow.strip(),
            "target_tier": tier,
            "target_environment": environment_name,
        },
        primary_success=True,
    )


__all__ = [
    "handle_deployment_run_approve",
    "handle_deployment_run_create",
    "handle_deployment_run_get",
    "handle_deployment_run_list",
    "handle_deployment_run_update",
    "handle_deployment_run_resolve_target",
]
