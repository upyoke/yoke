"""Handler for ``projects.environment.update``.

Renames an existing environment row in place. The current registered name
selects the row within its project; numeric ids never cross the boundary.
"""

from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class ProjectsEnvironmentUpdateRequest(BaseModel):
    project: str
    environment: str
    name: str


class ProjectsEnvironmentUpdateResponse(BaseModel):
    project: str
    environment: str
    previous_name: str


def handle_projects_environment_update(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    payload = request.payload or {}
    for key in ("project", "environment", "name"):
        value = payload.get(key)
        if not value or not isinstance(value, str):
            return _failure(
                "payload_invalid", f"{key} is required", f"$.payload.{key}",
            )
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.environment_reference import (
        EnvironmentReferenceError,
        resolve,
        validate_name,
    )
    from yoke_core.domain.project_identity import placeholder, resolve_project_id

    try:
        name = validate_name(str(payload["name"]))
    except ValueError as exc:
        return _failure("payload_invalid", str(exc), "$.payload.name")

    project = str(payload["project"])
    environment = str(payload["environment"])
    conn = connect()
    try:
        try:
            project_id = resolve_project_id(conn, project)
        except LookupError as exc:
            return _failure("project_not_found", str(exc), "$.payload.project")
        p = placeholder(conn)
        try:
            selected = resolve(conn, project_id=project_id, name=environment)
        except EnvironmentReferenceError as exc:
            return _failure(
                "environment_not_found",
                str(exc),
                "$.payload.environment",
            )
        previous_name = selected.name
        if previous_name == name:
            return _outcome(project, name, previous_name)
        taken = conn.execute(
            f"SELECT id FROM environments WHERE project_id = {p} AND name = {p} "
            f"AND id <> {p}",
            (project_id, name, selected.id),
        ).fetchone()
        if taken is not None:
            return _failure(
                "environment_name_conflict",
                f"environment name {name!r} is already used in project {project!r}",
                "$.payload.name",
            )
        conn.execute(
            f"UPDATE environments SET name = {p} WHERE id = {p}",
            (name, selected.id),
        )
        conn.commit()
        return _outcome(project, name, previous_name)
    finally:
        conn.close()


def _outcome(
    project: str, environment: str, previous_name: str,
) -> HandlerOutcome:
    return HandlerOutcome(
        result_payload=ProjectsEnvironmentUpdateResponse(
            project=project,
            environment=environment,
            previous_name=previous_name,
        ).model_dump(),
        primary_success=True,
    )


def _failure(code: str, message: str, jsonpath: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath=jsonpath),
    )


REGISTRATION_SPECS: List[Dict[str, Any]] = [
    {
        "function_id": "projects.environment.update",
        "handler": handle_projects_environment_update,
        "request_model": ProjectsEnvironmentUpdateRequest,
        "response_model": ProjectsEnvironmentUpdateResponse,
        "side_effects": ["environments_update"],
        "owner_module": (
            "yoke_core.domain.handlers.projects_infrastructure_update"
        ),
    },
]


__all__ = [
    "ProjectsEnvironmentUpdateRequest",
    "ProjectsEnvironmentUpdateResponse",
    "REGISTRATION_SPECS",
    "handle_projects_environment_update",
]
