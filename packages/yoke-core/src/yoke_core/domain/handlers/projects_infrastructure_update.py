"""Handler for ``projects.environment.update``.

Renames an existing environment row in place. Row id and site stay
stable; only the display ``name`` changes. Names are the closed
delivery set ``prod`` / ``stage``.
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
    environment_id: str
    name: str


class ProjectsEnvironmentUpdateResponse(BaseModel):
    project: str
    environment_id: str
    name: str
    previous_name: str


def handle_projects_environment_update(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    payload = request.payload or {}
    for key in ("project", "environment_id", "name"):
        value = payload.get(key)
        if not value or not isinstance(value, str):
            return _failure(
                "payload_invalid", f"{key} is required", f"$.payload.{key}",
            )
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.environment_delivery_record import (
        require_delivery_env_name,
    )
    from yoke_core.domain.project_identity import placeholder, resolve_project_id

    try:
        name = require_delivery_env_name(str(payload["name"]))
    except ValueError as exc:
        return _failure("payload_invalid", str(exc), "$.payload.name")

    project = str(payload["project"])
    environment_id = str(payload["environment_id"])
    conn = connect()
    try:
        try:
            project_id = resolve_project_id(conn, project)
        except LookupError as exc:
            return _failure("project_not_found", str(exc), "$.payload.project")
        p = placeholder(conn)
        row = conn.execute(
            "SELECT e.name, e.site, s.project_id FROM environments e "
            f"JOIN sites s ON s.id = e.site WHERE e.id = {p}",
            (environment_id,),
        ).fetchone()
        if row is None:
            return _failure(
                "environment_not_found",
                f"environment {environment_id!r} was not found",
                "$.payload.environment_id",
            )
        if int(row[2]) != project_id:
            return _failure(
                "environment_project_mismatch",
                f"environment {environment_id!r} belongs to another project",
                "$.payload.environment_id",
            )
        previous_name = str(row[0])
        if previous_name == name:
            return _outcome(project, environment_id, name, previous_name)
        taken = conn.execute(
            f"SELECT id FROM environments WHERE site = {p} AND name = {p} "
            f"AND id <> {p}",
            (str(row[1]), name, environment_id),
        ).fetchone()
        if taken is not None:
            return _failure(
                "environment_name_conflict",
                f"environment name {name!r} is already used on site "
                f"{str(row[1])!r}",
                "$.payload.name",
            )
        conn.execute(
            f"UPDATE environments SET name = {p} WHERE id = {p}",
            (name, environment_id),
        )
        conn.commit()
        return _outcome(project, environment_id, name, previous_name)
    finally:
        conn.close()


def _outcome(
    project: str, environment_id: str, name: str, previous_name: str,
) -> HandlerOutcome:
    return HandlerOutcome(
        result_payload=ProjectsEnvironmentUpdateResponse(
            project=project,
            environment_id=environment_id,
            name=name,
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
