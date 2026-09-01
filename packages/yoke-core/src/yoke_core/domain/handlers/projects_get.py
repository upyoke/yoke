"""``projects.get``/``projects.list`` handlers.

Wraps ``yoke_core.domain.projects_crud`` reads and converts pipe-delimited
or single-value returns into structured function responses.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_core.domain.actor_project_visibility import (
    actor_visible_project_ids,
    numeric_actor_id,
)
from yoke_core.domain.handlers.projects_resolve import (
    ProjectsResolveByGithubRepoRequest,
    ProjectsResolveByGithubRepoResponse,
    handle_projects_resolve_by_github_repo as _handle_projects_resolve,
)


class ProjectsGetRequest(BaseModel):
    project: str
    field: Optional[str] = None


class ProjectsGetResponse(BaseModel):
    project: str
    field: Optional[str] = None
    value: Optional[str] = None
    row: Optional[Dict[str, Any]] = None


class ProjectsListRequest(BaseModel):
    fields: Optional[List[str]] = None
    include_summary: bool = False


class ProjectsListResponse(BaseModel):
    fields: List[str]
    rows: List[Dict[str, Any]]


def handle_projects_get(request: FunctionCallRequest) -> HandlerOutcome:
    payload = request.payload or {}
    project = payload.get("project")
    field = payload.get("field")

    if not project or not isinstance(project, str):
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="payload_invalid",
                message="project is required",
                jsonpath="$.payload.project",
            ),
        )
    if field is not None and not isinstance(field, str):
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="payload_invalid",
                message="field must be a string when present",
                jsonpath="$.payload.field",
            ),
        )

    from yoke_core.domain.project_public_prefix import typed_project_field
    from yoke_core.domain.projects import PROJECT_FIELDS
    from yoke_core.domain.projects_crud import cmd_get

    resolved_project = project
    actor_id = numeric_actor_id(request.actor.actor_id if request.actor else None)
    if actor_id is not None:
        from yoke_core.domain.db_helpers import connect
        from yoke_core.domain.project_identity import resolve_project

        conn = connect()
        try:
            visible_project_ids = actor_visible_project_ids(conn, actor_id)
            identity = resolve_project(
                conn,
                project,
                required=False,
                visible_project_ids=visible_project_ids,
            )
        finally:
            conn.close()
        if identity is None:
            return HandlerOutcome(
                primary_success=False,
                error=FunctionError(
                    code="not_found",
                    message=f"project '{project}' not found",
                    jsonpath="$.payload.project",
                ),
            )
        resolved_project = str(identity.id)

    try:
        raw = cmd_get(resolved_project, field=field)
    except ValueError:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="invalid_field",
                message=(
                    f"unknown field '{field}' on projects table. "
                    f"Valid fields: {' '.join(PROJECT_FIELDS)}"
                ),
                jsonpath="$.payload.field",
            ),
        )
    except LookupError:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="not_found",
                message=f"project '{project}' not found",
                jsonpath="$.payload.project",
            ),
        )

    if raw is None:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="not_found",
                message=f"project '{project}' not found",
                jsonpath="$.payload.project",
            ),
        )

    if field:
        return HandlerOutcome(
            result_payload={
                "project": project,
                "field": field,
                "value": typed_project_field(field, raw),
            },
            primary_success=True,
        )

    # Full-row mode — cmd_get returns _pipe_row on PROJECT_FIELDS column order.
    parts = raw.split("|")
    row: Dict[str, Any] = {
        name: typed_project_field(name, val) for name, val in zip(PROJECT_FIELDS, parts)
    }
    return HandlerOutcome(
        result_payload={"project": project, "row": row},
        primary_success=True,
    )


def handle_projects_list(request: FunctionCallRequest) -> HandlerOutcome:
    from yoke_core.domain.projects import PROJECT_FIELDS, _PROJECT_LIST_FIELDS
    from yoke_core.domain.db_helpers import connect, query_rows
    from yoke_core.domain.project_public_prefix import typed_project_field
    from yoke_core.domain.project_summary_read import (
        PROJECT_SUMMARY_BASE_FIELDS,
        PROJECT_SUMMARY_FIELDS,
        enrich_project_summaries,
    )
    from yoke_core.domain.projects_crud import cmd_list

    actor_id = numeric_actor_id(request.actor.actor_id if request.actor else None)
    try:
        parsed = ProjectsListRequest(**(request.payload or {}))
    except Exception as exc:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="payload_invalid",
                message=str(exc),
                jsonpath="$.payload",
            ),
        )
    fields = tuple(
        parsed.fields
        or (
            PROJECT_SUMMARY_BASE_FIELDS
            if parsed.include_summary
            else _PROJECT_LIST_FIELDS
        )
    )
    invalid = [field for field in fields if field not in PROJECT_FIELDS]
    if invalid:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="invalid_field",
                message=(
                    f"unknown fields on projects table: {', '.join(invalid)}. "
                    f"Valid fields: {' '.join(PROJECT_FIELDS)}"
                ),
                jsonpath="$.payload.fields",
            ),
        )
    visible_project_ids = None
    rows: List[Dict[str, Any]] = []
    if actor_id is not None:
        conn = connect()
        try:
            visible_project_ids = actor_visible_project_ids(conn, actor_id)
        finally:
            conn.close()
    if parsed.fields is None and not parsed.include_summary:
        raw = cmd_list()
        raw_rows: list[Dict[str, Any]] = []
        for line in raw.splitlines():
            if not line:
                continue
            raw_rows.append(
                {
                    name: typed_project_field(name, val)
                    for name, val in zip(fields, line.split("|"))
                }
            )
    else:
        conn = connect()
        try:
            raw_rows = [
                {field: typed_project_field(field, row[field]) for field in fields}
                for row in query_rows(
                    conn,
                    f"SELECT {', '.join(fields)} FROM projects ORDER BY id ASC",
                )
            ]
            if parsed.include_summary:
                if visible_project_ids is not None:
                    raw_rows = [
                        row
                        for row in raw_rows
                        if int(row.get("id") or 0) in visible_project_ids
                    ]
                raw_rows = enrich_project_summaries(conn, raw_rows)
        finally:
            conn.close()
    for row in raw_rows:
        if visible_project_ids is not None:
            try:
                project_id = int(row.get("id") or 0)
            except (TypeError, ValueError):
                project_id = 0
            if project_id not in visible_project_ids:
                continue
        rows.append(row)
    return HandlerOutcome(
        result_payload={
            "fields": [
                *fields,
                *(PROJECT_SUMMARY_FIELDS if parsed.include_summary else ()),
            ],
            "rows": rows,
        },
        primary_success=True,
    )


def handle_projects_resolve_by_github_repo(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    """Resolve by repository while preserving the handler's patch seam."""
    return _handle_projects_resolve(
        request,
        visibility_reader=actor_visible_project_ids,
    )


__all__ = [
    "ProjectsGetRequest",
    "ProjectsGetResponse",
    "ProjectsListRequest",
    "ProjectsListResponse",
    "ProjectsResolveByGithubRepoRequest",
    "ProjectsResolveByGithubRepoResponse",
    "handle_projects_get",
    "handle_projects_list",
    "handle_projects_resolve_by_github_repo",
]
