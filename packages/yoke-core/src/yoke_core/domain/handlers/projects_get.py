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


class ProjectsListResponse(BaseModel):
    fields: List[str]
    rows: List[Dict[str, Any]]


class ProjectsResolveByGithubRepoRequest(BaseModel):
    github_repo: str


class ProjectsResolveByGithubRepoResponse(BaseModel):
    github_repo: str
    row: Optional[Dict[str, Any]] = None


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
            result_payload={"project": project, "field": field, "value": raw},
            primary_success=True,
        )

    # Full-row mode — cmd_get returns _pipe_row on PROJECT_FIELDS column order.
    parts = raw.split("|")
    row: Dict[str, Any] = {
        name: (val if val != "" else None)
        for name, val in zip(PROJECT_FIELDS, parts)
    }
    return HandlerOutcome(
        result_payload={"project": project, "row": row},
        primary_success=True,
    )


def handle_projects_list(request: FunctionCallRequest) -> HandlerOutcome:
    from yoke_core.domain.projects import PROJECT_FIELDS, _PROJECT_LIST_FIELDS
    from yoke_core.domain.db_helpers import connect, query_rows
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
    fields = tuple(parsed.fields or _PROJECT_LIST_FIELDS)
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
    if parsed.fields is None:
        raw = cmd_list()
        raw_rows: list[Dict[str, Any]] = []
        for line in raw.splitlines():
            if not line:
                continue
            raw_rows.append({
                name: (val if val != "" else None)
                for name, val in zip(fields, line.split("|"))
            })
    else:
        conn = connect()
        try:
            raw_rows = [
                {
                    field: row[field] if row[field] != "" else None
                    for field in fields
                }
                for row in query_rows(
                    conn,
                    f"SELECT {', '.join(fields)} FROM projects ORDER BY id ASC",
                )
            ]
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
        result_payload={"fields": list(fields), "rows": rows},
        primary_success=True,
    )


def handle_projects_resolve_by_github_repo(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    from yoke_core.domain.db_helpers import connect, query_rows
    from yoke_core.domain.project_github_binding import normalize_github_repo
    from yoke_core.domain.projects import PROJECT_FIELDS

    try:
        parsed = ProjectsResolveByGithubRepoRequest(**(request.payload or {}))
    except Exception as exc:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="payload_invalid",
                message=str(exc),
                jsonpath="$.payload",
            ),
        )
    wanted = normalize_github_repo(parsed.github_repo)
    if not wanted:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="payload_invalid",
                message="github_repo must be a GitHub owner/repo or clone URL",
                jsonpath="$.payload.github_repo",
            ),
        )

    actor_id = numeric_actor_id(request.actor.actor_id if request.actor else None)
    conn = connect()
    try:
        visible_project_ids = actor_visible_project_ids(conn, actor_id)
        rows = query_rows(
            conn,
            f"SELECT {', '.join(PROJECT_FIELDS)} FROM projects ORDER BY id ASC",
        )
    finally:
        conn.close()

    matching_rows = [
        row
        for row in rows
        if normalize_github_repo(row.get("github_repo")) == wanted
    ]
    if matching_rows:
        visible_rows = matching_rows
        if visible_project_ids is not None:
            visible_rows = [
                row
                for row in matching_rows
                if _row_project_id(row) in visible_project_ids
            ]
        if len(visible_rows) == 1:
            row = visible_rows[0]
            return HandlerOutcome(
                result_payload={
                    "github_repo": wanted,
                    "row": {
                        field: row[field] if row[field] != "" else None
                        for field in PROJECT_FIELDS
                    },
                },
                primary_success=True,
            )
        if len(visible_rows) > 1:
            return HandlerOutcome(
                primary_success=False,
                error=FunctionError(
                    code="ambiguous_project",
                    message=(
                        f"Multiple visible Yoke projects are registered for "
                        f"{wanted}; resolve by numeric project id."
                    ),
                    jsonpath="$.payload.github_repo",
                ),
            )
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="permission_denied",
                message=(
                    f"A Yoke project is registered for {wanted}, but this "
                    "API token does not have access to that project."
                ),
                jsonpath="$.payload.github_repo",
            ),
        )
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(
            code="not_found",
            message=f"No Yoke project is registered for {wanted}.",
            jsonpath="$.payload.github_repo",
        ),
    )


def _row_project_id(row: Dict[str, Any]) -> int:
    try:
        return int(row.get("id") or 0)
    except (TypeError, ValueError):
        return 0


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
