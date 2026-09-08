"""Service boundary for the dedicated deployment-runs history page."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_core.domain.handlers.deployment_common import error


RUN_PAGE_SIZE = 50
MAX_RUN_PAGE_SIZE = 100


class DeploymentRunPageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    projects: list[str] | None = None
    search: str | None = Field(default=None, max_length=200)
    status: str | None = None
    environment: str | None = None
    flow: str | None = None
    page_size: int = Field(default=RUN_PAGE_SIZE, ge=1, le=MAX_RUN_PAGE_SIZE)
    cursor: str | None = None


def _validation_error(exc: ValidationError) -> HandlerOutcome:
    issue = exc.errors()[0]
    path = ".".join(str(part) for part in issue.get("loc", ()))
    return error(
        "payload_invalid",
        "Runs page request invalid: "
        f"{issue.get('msg')}; clear the cursor and reload the first Runs page",
        jsonpath=f"$.payload.page{'.' + path if path else ''}",
    )


def handle_deployment_run_page(
    request: FunctionCallRequest,
    raw_page: Any,
) -> HandlerOutcome:
    """Return one authorized unfinished-plus-completed history page."""
    try:
        page = DeploymentRunPageRequest.model_validate(raw_page)
    except ValidationError as exc:
        return _validation_error(exc)

    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.deployment_run_history_read import (
        RunHistoryCursorError,
        read_deployment_run_history,
    )
    from yoke_core.domain.handlers.items_project_scope import (
        actor_visible_scope,
        ambiguous_project_error,
        resolve_visible_project_ids,
    )
    from yoke_core.domain.project_identity import AmbiguousProjectRefError

    conn = connect()
    try:
        visible = actor_visible_scope(conn, request)
        try:
            project_ids = resolve_visible_project_ids(
                conn,
                page.projects,
                visible,
            )
        except AmbiguousProjectRefError as exc:
            return ambiguous_project_error(str(exc), "$.payload.page.projects")
        if project_ids is None and visible is not None:
            project_ids = sorted(visible)
        actor = request.actor.actor_id if request.actor else None
        actor_id = int(actor) if actor is not None and str(actor).isdigit() else None
        try:
            result = read_deployment_run_history(
                conn,
                project_ids=project_ids,
                search=page.search,
                status=page.status,
                environment=page.environment,
                flow=page.flow,
                page_size=page.page_size,
                cursor=page.cursor,
                actor_id=actor_id,
            )
        except RunHistoryCursorError as exc:
            return error(
                "invalid_cursor",
                str(exc),
                jsonpath="$.payload.page.cursor",
            )
    finally:
        conn.close()
    return HandlerOutcome(result_payload=result, primary_success=True)


__all__ = [
    "MAX_RUN_PAGE_SIZE",
    "RUN_PAGE_SIZE",
    "DeploymentRunPageRequest",
    "handle_deployment_run_page",
]
