"""Deployment run read/update handlers."""

from __future__ import annotations

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    HandlerOutcome,
)

from yoke_core.domain.handlers.deployment_common import (
    error,
    pipe_rows,
    pipe_to_dict,
    require_global,
    run_id,
)


def handle_deployment_run_get(request: FunctionCallRequest) -> HandlerOutcome:
    resolved_run_id = run_id(request, "deployment_runs.get")
    if isinstance(resolved_run_id, HandlerOutcome):
        return resolved_run_id
    payload = request.payload or {}
    field = payload.get("field")
    if field is not None and not isinstance(field, str):
        return error(
            "payload_invalid", "field must be a string when present",
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
    return HandlerOutcome(
        result_payload={
            "run_id": resolved_run_id,
            "fields": list(RUN_FIELDS),
            "run": pipe_to_dict(raw, RUN_FIELDS),
        },
        primary_success=True,
    )


def handle_deployment_run_create(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    """Create a zero-member environment deployment run.

    Item-bound delivery keeps using ``runs start-for-item``; this surface
    exists for attended environment administration and recovery, where the
    run must exist in the control plane before the pipeline is driven —
    previously only reachable through direct database administration.
    """
    invalid = require_global(request, "deployment_runs.create")
    if invalid is not None:
        return invalid
    payload = request.payload or {}
    project = payload.get("project")
    flow = payload.get("flow")
    target_env = payload.get("target_env")
    created_by = payload.get("created_by") or "operator"
    for key, value, required in (
        ("project", project, True),
        ("flow", flow, True),
        ("target_env", target_env, False),
        ("created_by", created_by, True),
    ):
        if required and (not isinstance(value, str) or not value.strip()):
            return error(
                "payload_invalid",
                f"{key} must be a non-empty string",
                jsonpath=f"$.payload.{key}",
            )
        if not required and value is not None and not isinstance(value, str):
            return error(
                "payload_invalid",
                f"{key} must be a string when present",
                jsonpath=f"$.payload.{key}",
            )

    from yoke_core.domain.deployment_runs_crud_mutate import cmd_create_run
    from yoke_core.domain.deployment_runs_crud_query import cmd_get
    from yoke_core.domain.deployment_runs_schema import RUN_FIELDS

    try:
        created_run_id = cmd_create_run(
            project.strip(),
            flow.strip(),
            target_env=(target_env or "").strip() or None,
            created_by=created_by.strip(),
        )
    except LookupError as exc:
        return error("not_found", str(exc), jsonpath="$.payload.flow")
    except ValueError as exc:
        return error("run_create_rejected", str(exc), jsonpath="$.payload")
    created = pipe_to_dict(cmd_get(created_run_id), RUN_FIELDS)
    return HandlerOutcome(
        result_payload={
            "run_id": created_run_id,
            "project": created.get("project") or project.strip(),
            "flow": created.get("flow") or flow.strip(),
            "target_env": created.get("target_env") or None,
            "status": created.get("status") or "created",
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
    for key, value in (("project", project), ("status", status)):
        if value is not None and not isinstance(value, str):
            return error(
                "payload_invalid",
                f"{key} must be a string when present",
                jsonpath=f"$.payload.{key}",
            )

    from yoke_core.domain.deployment_runs_crud_query import cmd_list
    from yoke_core.domain.deployment_runs_schema import RUN_FIELDS

    raw = cmd_list(project=project, status=status)
    return HandlerOutcome(
        result_payload={
            "fields": list(RUN_FIELDS),
            "rows": pipe_rows(raw, RUN_FIELDS),
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
            "payload_invalid", "field is required",
            jsonpath="$.payload.field",
        )
    if value is None:
        return error(
            "payload_invalid", "value is required",
            jsonpath="$.payload.value",
        )

    from yoke_core.domain.deployment_runs_crud_mutate import cmd_update

    err = cmd_update(resolved_run_id, field.strip(), str(value), force=force)
    if err:
        lower = err.lower()
        if "not found" in lower:
            return error(
                "not_found", err, jsonpath="$.target.workflow_run_id",
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
        approval = approve_run(resolved_run_id)
    except LookupError as exc:
        return error("not_found", str(exc), jsonpath="$.target.workflow_run_id")
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
            "event_id": event_id,
        },
        primary_success=True,
    )


def handle_deployment_run_resolve_target_env(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    invalid = require_global(request, "deployment_runs.resolve_target_env")
    if invalid is not None:
        return invalid
    payload = request.payload or {}
    project = payload.get("project")
    flow = payload.get("flow")
    target_env = payload.get("target_env")
    if not isinstance(project, str) or not project.strip():
        return error(
            "payload_invalid", "project is required",
            jsonpath="$.payload.project",
        )
    if not isinstance(flow, str) or not flow.strip():
        return error(
            "payload_invalid", "flow is required",
            jsonpath="$.payload.flow",
        )
    if target_env is not None and not isinstance(target_env, str):
        return error(
            "payload_invalid",
            "target_env must be a string when present",
            jsonpath="$.payload.target_env",
        )

    from yoke_core.domain.deployment_runs_preview import cmd_resolve_target_env

    try:
        resolved = cmd_resolve_target_env(
            project.strip(),
            flow.strip(),
            target_env_override=target_env,
        )
    except LookupError as exc:
        return error("not_found", str(exc))
    except ValueError as exc:
        return error("payload_invalid", str(exc))
    return HandlerOutcome(
        result_payload={
            "project": project.strip(),
            "flow": flow.strip(),
            "target_env": resolved,
        },
        primary_success=True,
    )


__all__ = [
    "handle_deployment_run_approve",
    "handle_deployment_run_get",
    "handle_deployment_run_list",
    "handle_deployment_run_update",
    "handle_deployment_run_resolve_target_env",
]
