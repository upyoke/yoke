"""Registered creation of itemless deployment runs and pinned retries."""

from __future__ import annotations

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_core.domain.handlers.deployment_common import (
    error,
    pipe_to_dict,
    require_global,
)


def _retry_lineage(run_id: str, *, project: str, flow: str) -> str:
    from yoke_core.domain.deployment_runs_crud_query import cmd_get
    from yoke_core.domain.deployment_runs_schema import RUN_FIELDS

    raw = cmd_get(run_id)
    if raw is None:
        raise LookupError(f"deployment run {run_id!r} not found")
    source = pipe_to_dict(raw, RUN_FIELDS)
    if source["project"] != project or source["flow"] != flow:
        raise ValueError(
            f"retry source {run_id!r} belongs to project "
            f"{source['project']!r}, flow {source['flow']!r}"
        )
    if source["status"] not in {"failed", "cancelled"}:
        raise ValueError(
            f"retry source {run_id!r} has non-terminal status "
            f"{source['status']!r}"
        )
    lineage = (source["release_lineage"] or "").strip()
    if not lineage:
        raise ValueError(
            f"retry source {run_id!r} has no pinned release lineage"
        )
    return lineage


def handle_deployment_run_create(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    """Create a zero-member run, optionally reusing a terminal run's lineage."""
    invalid = require_global(request, "deployment_runs.create")
    if invalid is not None:
        return invalid
    payload = request.payload or {}
    project = payload.get("project")
    flow = payload.get("flow")
    environment = payload.get("environment")
    release_lineage = payload.get("release_lineage")
    retry_of = payload.get("retry_of")
    created_by = payload.get("created_by") or "operator"
    for key, value, required in (
        ("project", project, True),
        ("flow", flow, True),
        ("environment", environment, False),
        ("release_lineage", release_lineage, False),
        ("retry_of", retry_of, False),
        ("created_by", created_by, True),
    ):
        if required and (not isinstance(value, str) or not value.strip()):
            return error(
                "payload_invalid", f"{key} must be a non-empty string",
                jsonpath=f"$.payload.{key}",
            )
        if not required and value is not None and not isinstance(value, str):
            return error(
                "payload_invalid", f"{key} must be a string when present",
                jsonpath=f"$.payload.{key}",
            )
    if retry_of and release_lineage:
        return error(
            "payload_invalid",
            "retry_of and release_lineage are mutually exclusive",
            jsonpath="$.payload",
        )

    clean_project = project.strip()
    clean_flow = flow.strip()
    try:
        if retry_of:
            release_lineage = _retry_lineage(
                retry_of.strip(), project=clean_project, flow=clean_flow,
            )
        from yoke_core.domain.deployment_runs_crud_mutate import cmd_create_run

        created_run_id = cmd_create_run(
            clean_project,
            clean_flow,
            environment=(environment or "").strip() or None,
            release_lineage=(release_lineage or "").strip() or None,
            created_by=created_by.strip(),
        )
    except LookupError as exc:
        return error("not_found", str(exc), jsonpath="$.payload")
    except ValueError as exc:
        return error("run_create_rejected", str(exc), jsonpath="$.payload")

    from yoke_core.domain.deployment_runs_crud_query import cmd_get
    from yoke_core.domain.deployment_runs_schema import RUN_FIELDS

    created = pipe_to_dict(cmd_get(created_run_id), RUN_FIELDS)
    return HandlerOutcome(
        result_payload={
            "run_id": created_run_id,
            "project": created.get("project") or clean_project,
            "flow": created.get("flow") or clean_flow,
            "target_tier": created.get("target_tier") or None,
            "target_environment": created.get("target_environment") or None,
            "release_lineage": created.get("release_lineage") or None,
            "status": created.get("status") or "created",
        },
        primary_success=True,
    )


__all__ = ["handle_deployment_run_create"]
