"""Metadata-only project site and environment inventory handler."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class ProjectsInfrastructureListRequest(BaseModel):
    project: str


class ProjectsInfrastructureListResponse(BaseModel):
    project: str
    sites: list[dict[str, Any]]
    environments: list[dict[str, Any]]


def handle_projects_infrastructure_list(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    """List non-secret site and environment metadata for one project."""
    try:
        parsed = ProjectsInfrastructureListRequest(**(request.payload or {}))
    except Exception as exc:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="payload_invalid",
                message=str(exc),
                jsonpath="$.payload",
            ),
        )

    from yoke_core.domain.db_helpers import connect, query_rows
    from yoke_core.domain.project_identity import resolve_project_id

    conn = connect()
    try:
        try:
            project_id = resolve_project_id(conn, parsed.project)
        except LookupError:
            return HandlerOutcome(
                primary_success=False,
                error=FunctionError(
                    code="not_found",
                    message=f"project {parsed.project!r} not found",
                    jsonpath="$.payload.project",
                ),
            )
        sites = query_rows(
            conn,
            "SELECT id, name, description FROM sites "
            "WHERE project_id = %s ORDER BY id",
            (project_id,),
        )
        environments = query_rows(
            conn,
            "SELECT e.id, e.site, e.name, e.url, e.deploy_method, "
            "e.health_check_url FROM environments e "
            "JOIN sites s ON s.id = e.site "
            "WHERE s.project_id = %s ORDER BY e.site, e.id",
            (project_id,),
        )
    finally:
        conn.close()

    return HandlerOutcome(
        primary_success=True,
        result_payload={
            "project": parsed.project,
            "sites": [dict(row) for row in sites],
            "environments": [dict(row) for row in environments],
        },
    )


__all__ = [
    "ProjectsInfrastructureListRequest",
    "ProjectsInfrastructureListResponse",
    "handle_projects_infrastructure_list",
]
