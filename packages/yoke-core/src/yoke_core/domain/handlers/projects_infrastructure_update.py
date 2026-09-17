"""Handler for ``projects.environment.update``.

Updates an existing environment row in place. The current registered name
selects the row within its project; numeric ids never cross the boundary.
``name`` and ``url`` are independently optional; at least one must be set.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class ProjectsEnvironmentUpdateRequest(BaseModel):
    project: str
    environment: str
    name: Optional[str] = None
    url: Optional[str] = None


class ProjectsEnvironmentUpdateResponse(BaseModel):
    project: str
    environment: str
    previous_name: str


def handle_projects_environment_update(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    payload = request.payload or {}
    for key in ("project", "environment"):
        value = payload.get(key)
        if not value or not isinstance(value, str):
            return _failure(
                "payload_invalid", f"{key} is required", f"$.payload.{key}",
            )
    name_raw = payload.get("name")
    url_raw = payload.get("url")
    if not name_raw and url_raw is None:
        return _failure(
            "payload_invalid",
            "name or url is required",
            "$.payload",
        )
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.environment_reference import (
        EnvironmentReferenceError,
        resolve,
        validate_name,
    )
    from yoke_core.domain.project_identity import placeholder, resolve_project_id

    name: Optional[str] = None
    if name_raw is not None:
        try:
            name = validate_name(str(name_raw))
        except ValueError as exc:
            return _failure("payload_invalid", str(exc), "$.payload.name")
    url: Optional[str] = None
    if url_raw is not None:
        from yoke_core.domain.environment_registered_url import (
            normalize_registered_url,
        )

        try:
            url = normalize_registered_url(str(url_raw))
        except ValueError as exc:
            return _failure("payload_invalid", str(exc), "$.payload.url")

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
        new_name = previous_name
        assignments: list[str] = []
        params: list[Any] = []
        if name is not None and name != previous_name:
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
            assignments.append(f"name = {p}")
            params.append(name)
            new_name = name
        if url is not None:
            assignments.append(f"url = {p}")
            params.append(url)
        if assignments:
            params.append(selected.id)
            conn.execute(
                f"UPDATE environments SET {', '.join(assignments)} WHERE id = {p}",
                tuple(params),
            )
            conn.commit()
        return _outcome(project, new_name, previous_name)
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
