"""Handlers for ``projects.site.create`` / ``projects.environment.create``.

Idempotent infrastructure-registry writes addressed only by human names.
Re-running a create for an identity that already exists reports
``outcome="already_present"`` and touches nothing — settings included;
settings updates go through the dedicated settings surfaces. Site names and
environment names are unique inside one project; numeric row ids never cross
the function boundary.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_core.domain.json_helper import dumps_compact


class ProjectsSiteCreateRequest(BaseModel):
    project: str
    site: str
    settings: Optional[Dict[str, Any]] = None


class ProjectsSiteCreateResponse(BaseModel):
    project: str
    site: str
    outcome: str


class ProjectsEnvironmentCreateRequest(BaseModel):
    project: str
    site: str
    environment: str
    settings: Optional[Dict[str, Any]] = None


class ProjectsEnvironmentCreateResponse(BaseModel):
    project: str
    site: str
    environment: str
    outcome: str


OUTCOME_CREATED = "created"
OUTCOME_ALREADY_PRESENT = "already_present"


def handle_projects_site_create(request: FunctionCallRequest) -> HandlerOutcome:
    payload = request.payload or {}
    error = _require_strings(payload, ("project", "site"))
    if error is not None:
        return error
    error = _validate_settings(payload)
    if error is not None:
        return error
    from yoke_core.domain.db_helpers import connect, iso8601_now
    from yoke_core.domain.project_identity import placeholder, resolve_project_id

    project = str(payload["project"])
    site_name = str(payload["site"]).strip()
    conn = connect()
    try:
        try:
            project_id = resolve_project_id(conn, project)
        except LookupError as exc:
            return _failure("project_not_found", str(exc), "$.payload.project")
        p = placeholder(conn)
        row = conn.execute(
            f"SELECT id FROM sites WHERE project_id = {p} AND name = {p}",
            (project_id, site_name),
        ).fetchone()
        if row is not None:
            return _site_outcome(project, site_name, OUTCOME_ALREADY_PRESENT)
        conn.execute(
            "INSERT INTO sites (project_id, name, created_at, settings) "
            f"VALUES ({p}, {p}, {p}, {p})",
            (
                project_id,
                site_name,
                iso8601_now(),
                dumps_compact(payload.get("settings") or {}),
            ),
        )
        conn.commit()
        return _site_outcome(project, site_name, OUTCOME_CREATED)
    finally:
        conn.close()


def handle_projects_environment_create(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    payload = request.payload or {}
    error = _require_strings(payload, ("project", "site", "environment"))
    if error is not None:
        return error
    error = _validate_settings(payload)
    if error is not None:
        return error
    from yoke_core.domain.db_helpers import connect, iso8601_now
    from yoke_core.domain.project_identity import placeholder, resolve_project_id

    project = str(payload["project"])
    site_name = str(payload["site"]).strip()
    from yoke_core.domain.environment_reference import validate_name
    try:
        environment_name = validate_name(str(payload["environment"]))
    except ValueError as exc:
        return _failure("payload_invalid", str(exc), "$.payload.environment")
    conn = connect()
    try:
        try:
            project_id = resolve_project_id(conn, project)
        except LookupError as exc:
            return _failure("project_not_found", str(exc), "$.payload.project")
        p = placeholder(conn)
        site = conn.execute(
            f"SELECT id FROM sites WHERE project_id = {p} AND name = {p}",
            (project_id, site_name),
        ).fetchone()
        if site is None:
            return _failure(
                "site_not_found",
                f"site {site_name!r} was not found; create it first with "
                "projects.site.create",
                "$.payload.site",
            )
        existing = conn.execute(
            f"SELECT site FROM environments WHERE project_id = {p} AND name = {p}",
            (project_id, environment_name),
        ).fetchone()
        if existing is not None:
            if int(existing[0]) != int(site[0]):
                return _failure(
                    "environment_site_mismatch",
                    f"environment {environment_name!r} already belongs to "
                    "another site",
                    "$.payload.environment",
                )
            return _environment_outcome(
                project, site_name, environment_name, OUTCOME_ALREADY_PRESENT,
            )
        conn.execute(
            "INSERT INTO environments "
            "(site, project_id, name, created_at, settings) "
            f"VALUES ({p}, {p}, {p}, {p}, {p})",
            (
                int(site[0]),
                project_id,
                environment_name,
                iso8601_now(),
                dumps_compact(payload.get("settings") or {}),
            ),
        )
        conn.commit()
        return _environment_outcome(
            project, site_name, environment_name, OUTCOME_CREATED,
        )
    finally:
        conn.close()


def _site_outcome(project: str, site: str, outcome: str) -> HandlerOutcome:
    return HandlerOutcome(
        result_payload=ProjectsSiteCreateResponse(
            project=project, site=site, outcome=outcome,
        ).model_dump(),
        primary_success=True,
    )


def _environment_outcome(
    project: str, site: str, environment: str, outcome: str,
) -> HandlerOutcome:
    return HandlerOutcome(
        result_payload=ProjectsEnvironmentCreateResponse(
            site=site, environment=environment, outcome=outcome,
            project=project,
        ).model_dump(),
        primary_success=True,
    )


def _require_strings(
    payload: dict[str, Any], keys: tuple[str, ...]
) -> Optional[HandlerOutcome]:
    for key in keys:
        value = payload.get(key)
        if not value or not isinstance(value, str):
            return _failure(
                "payload_invalid", f"{key} is required", f"$.payload.{key}",
            )
    return None


def _validate_settings(payload: dict[str, Any]) -> Optional[HandlerOutcome]:
    settings = payload.get("settings")
    if settings is not None and not isinstance(settings, dict):
        return _failure(
            "payload_invalid",
            "settings must be a JSON object",
            "$.payload.settings",
        )
    return None


def _failure(code: str, message: str, jsonpath: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath=jsonpath),
    )


REGISTRATION_SPECS: List[Dict[str, Any]] = [
    {
        "function_id": "projects.site.create",
        "handler": handle_projects_site_create,
        "request_model": ProjectsSiteCreateRequest,
        "response_model": ProjectsSiteCreateResponse,
        "side_effects": ["sites_insert"],
        "owner_module": (
            "yoke_core.domain.handlers.projects_infrastructure_create"
        ),
    },
    {
        "function_id": "projects.environment.create",
        "handler": handle_projects_environment_create,
        "request_model": ProjectsEnvironmentCreateRequest,
        "response_model": ProjectsEnvironmentCreateResponse,
        "side_effects": ["environments_insert"],
        "owner_module": (
            "yoke_core.domain.handlers.projects_infrastructure_create"
        ),
    },
]


__all__ = [
    "OUTCOME_ALREADY_PRESENT",
    "OUTCOME_CREATED",
    "ProjectsEnvironmentCreateRequest",
    "ProjectsEnvironmentCreateResponse",
    "ProjectsSiteCreateRequest",
    "ProjectsSiteCreateResponse",
    "REGISTRATION_SPECS",
    "handle_projects_environment_create",
    "handle_projects_site_create",
]
