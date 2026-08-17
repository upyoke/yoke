"""Handlers for ``projects.site.create`` / ``projects.environment.create``.

Idempotent infrastructure-registry writes: a ``sites`` row keyed by its
slug and an ``environments`` row keyed by its id under a project-owned
site. Re-running a create for an identity that already exists reports
``outcome="already_present"`` and touches nothing — settings included;
settings updates go through the dedicated settings surfaces. A slug or
id already owned by a DIFFERENT project (or site) refuses with a
mismatch error instead of adopting the row. Environment ownership is
indirect (``environments.site -> sites.id -> sites.project_id``), so
the environment handler resolves through the site row.
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
    site_slug: str
    settings: Optional[Dict[str, Any]] = None


class ProjectsSiteCreateResponse(BaseModel):
    project: str
    site_id: str
    outcome: str


class ProjectsEnvironmentCreateRequest(BaseModel):
    project: str
    site_slug: str
    environment_id: str
    name: Optional[str] = None
    settings: Optional[Dict[str, Any]] = None


class ProjectsEnvironmentCreateResponse(BaseModel):
    project: str
    site_id: str
    environment_id: str
    name: str
    outcome: str


OUTCOME_CREATED = "created"
OUTCOME_ALREADY_PRESENT = "already_present"


def handle_projects_site_create(request: FunctionCallRequest) -> HandlerOutcome:
    payload = request.payload or {}
    error = _require_strings(payload, ("project", "site_slug"))
    if error is not None:
        return error
    error = _validate_settings(payload)
    if error is not None:
        return error
    from yoke_core.domain.db_helpers import connect, iso8601_now
    from yoke_core.domain.project_identity import placeholder, resolve_project_id

    project = str(payload["project"])
    site_slug = str(payload["site_slug"])
    conn = connect()
    try:
        try:
            project_id = resolve_project_id(conn, project)
        except LookupError as exc:
            return _failure("project_not_found", str(exc), "$.payload.project")
        p = placeholder(conn)
        row = conn.execute(
            f"SELECT project_id FROM sites WHERE id = {p}", (site_slug,)
        ).fetchone()
        if row is not None:
            if int(row[0]) != project_id:
                return _failure(
                    "site_project_mismatch",
                    f"site {site_slug!r} already belongs to another project",
                    "$.payload.site_slug",
                )
            return _site_outcome(project, site_slug, OUTCOME_ALREADY_PRESENT)
        conn.execute(
            "INSERT INTO sites (id, project_id, name, created_at, settings) "
            f"VALUES ({p}, {p}, {p}, {p}, {p})",
            (
                site_slug,
                project_id,
                site_slug,
                iso8601_now(),
                dumps_compact(payload.get("settings") or {}),
            ),
        )
        conn.commit()
        return _site_outcome(project, site_slug, OUTCOME_CREATED)
    finally:
        conn.close()


def handle_projects_environment_create(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    payload = request.payload or {}
    error = _require_strings(payload, ("project", "site_slug", "environment_id"))
    if error is not None:
        return error
    error = _validate_settings(payload)
    if error is not None:
        return error
    from yoke_core.domain.db_helpers import connect, iso8601_now
    from yoke_core.domain.project_identity import placeholder, resolve_project_id

    project = str(payload["project"])
    site_slug = str(payload["site_slug"])
    environment_id = str(payload["environment_id"])
    conn = connect()
    try:
        try:
            project_id = resolve_project_id(conn, project)
        except LookupError as exc:
            return _failure("project_not_found", str(exc), "$.payload.project")
        p = placeholder(conn)
        site = conn.execute(
            f"SELECT project_id FROM sites WHERE id = {p}", (site_slug,)
        ).fetchone()
        if site is None:
            return _failure(
                "site_not_found",
                f"site {site_slug!r} was not found; create it first with "
                "projects.site.create",
                "$.payload.site_slug",
            )
        if int(site[0]) != project_id:
            return _failure(
                "site_project_mismatch",
                f"site {site_slug!r} belongs to another project",
                "$.payload.site_slug",
            )
        existing = conn.execute(
            f"SELECT site, name FROM environments WHERE id = {p}",
            (environment_id,),
        ).fetchone()
        if existing is not None:
            if str(existing[0]) != site_slug:
                return _failure(
                    "environment_site_mismatch",
                    f"environment {environment_id!r} already belongs to "
                    "another site",
                    "$.payload.environment_id",
                )
            return _environment_outcome(
                project, site_slug, environment_id,
                str(existing[1]), OUTCOME_ALREADY_PRESENT,
            )
        try:
            name = _requested_environment_name(
                payload, site_slug, environment_id,
            )
        except ValueError as exc:
            return _failure("payload_invalid", str(exc), "$.payload.name")
        conn.execute(
            "INSERT INTO environments (id, site, name, created_at, settings) "
            f"VALUES ({p}, {p}, {p}, {p}, {p})",
            (
                environment_id,
                site_slug,
                name,
                iso8601_now(),
                dumps_compact(payload.get("settings") or {}),
            ),
        )
        conn.commit()
        return _environment_outcome(
            project, site_slug, environment_id, name, OUTCOME_CREATED,
        )
    finally:
        conn.close()


def _environment_name(site_slug: str, environment_id: str) -> str:
    """Display name: the environment id with the owning-site prefix removed."""
    leaf = environment_id.removeprefix(f"{site_slug}-")
    return leaf or environment_id


def _requested_environment_name(
    payload: dict[str, Any], site_slug: str, environment_id: str,
) -> str:
    raw_name = payload.get("name")
    if raw_name is None:
        return _environment_name(site_slug, environment_id)
    if not isinstance(raw_name, str) or not raw_name.strip():
        raise ValueError("name must be a non-empty string when present")
    from yoke_core.domain.environment_delivery_record import (
        require_delivery_env_name,
    )
    return require_delivery_env_name(raw_name)


def _site_outcome(project: str, site_slug: str, outcome: str) -> HandlerOutcome:
    return HandlerOutcome(
        result_payload=ProjectsSiteCreateResponse(
            project=project, site_id=site_slug, outcome=outcome,
        ).model_dump(),
        primary_success=True,
    )


def _environment_outcome(
    project: str, site_slug: str, environment_id: str, name: str, outcome: str,
) -> HandlerOutcome:
    return HandlerOutcome(
        result_payload=ProjectsEnvironmentCreateResponse(
            project=project, site_id=site_slug,
            environment_id=environment_id, name=name, outcome=outcome,
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
