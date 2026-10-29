"""Retirement admission for project writes on every dispatch transport."""

from dataclasses import replace

from yoke_core.domain.function_target_resolution import resolve_project_context
from yoke_core.domain.function_unresolved_project import permission_error_response
from yoke_core.domain.project_retirement import (
    project_is_retired,
    retired_project_recovery,
)


def check_retirement(conn, entry, request, permission):
    """Keep history readable while refusing new work in a retired project."""
    if permission.error is not None or not _requires_active_project(entry):
        return permission
    project_id = permission.project_id
    if project_id is None:
        context = resolve_project_context(conn, entry, request)
        project_id = context[0] if context else None
    if project_id is None or not project_is_retired(conn, project_id):
        return permission
    return replace(
        permission,
        error=permission_error_response(
            request,
            entry,
            "project_retired",
            retired_project_recovery(project_id),
        ),
    )


def _requires_active_project(entry):
    return (
        entry.function_id.startswith("items.") and bool(entry.side_effects)
    ) or entry.function_id in {
        "claims.work.acquire",
        "session_control.launch.create",
        "session_control.launch.retry",
        "deployment_runs.create",
    }
