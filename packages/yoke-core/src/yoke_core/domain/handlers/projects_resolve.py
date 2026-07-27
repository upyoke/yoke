"""Resolve a visible Yoke project by its normalized GitHub repository."""

from __future__ import annotations

from typing import Any, Dict, Optional

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


class ProjectsResolveByGithubRepoRequest(BaseModel):
    github_repo: str


class ProjectsResolveByGithubRepoResponse(BaseModel):
    github_repo: str
    row: Optional[Dict[str, Any]] = None


def _row_project_id(row: Dict[str, Any]) -> int:
    try:
        return int(row.get("id") or 0)
    except (TypeError, ValueError):
        return 0


def handle_projects_resolve_by_github_repo(
    request: FunctionCallRequest,
    *,
    visibility_reader=actor_visible_project_ids,
) -> HandlerOutcome:
    """Resolve exactly one repository-bound project visible to the caller."""
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
        visible_project_ids = visibility_reader(conn, actor_id)
        rows = query_rows(
            conn,
            f"SELECT {', '.join(PROJECT_FIELDS)} FROM projects ORDER BY id ASC",
        )
    finally:
        conn.close()

    matching_rows = [
        row for row in rows if normalize_github_repo(row.get("github_repo")) == wanted
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
                        "Multiple visible Yoke projects are registered for "
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


__all__ = [
    "ProjectsResolveByGithubRepoRequest",
    "ProjectsResolveByGithubRepoResponse",
    "handle_projects_resolve_by_github_repo",
]
