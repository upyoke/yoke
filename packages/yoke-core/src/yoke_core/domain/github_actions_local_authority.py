"""Narrow attended local authority for typed GitHub Actions operations."""

from __future__ import annotations

import os

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
    FunctionError,
)
from yoke_contracts.github_workflow_dispatch import (
    GITHUB_ACTIONS_LOCAL_AUTHORITY_ENV,
)
from yoke_core.domain.items_constants import DEFAULT_ITEM_ACTOR_ID


_ALLOWED_FUNCTIONS = frozenset({
    "github_actions.workflow.dispatch",
    "github_actions.workflow.dispatch_once",
    "github_actions.workflow.find_run",
    "github_actions.run.jobs_count",
    "github_actions.wait_run",
})


def _denied(request: FunctionCallRequest, message: str) -> FunctionCallResponse:
    return FunctionCallResponse(
        success=False,
        function=request.function,
        version=request.version,
        request_id=request.request_id,
        error=FunctionError(code="local_github_authority_denied", message=message),
    )


def dispatch(request: FunctionCallRequest) -> FunctionCallResponse:
    """Run only the workflow adapter family under explicit attended authority."""
    if os.environ.get(GITHUB_ACTIONS_LOCAL_AUTHORITY_ENV, "").strip() != "1":
        return _denied(
            request,
            f"{GITHUB_ACTIONS_LOCAL_AUTHORITY_ENV}=1 is required for local "
            "GitHub Actions authority",
        )
    if os.environ.get("GITHUB_ACTIONS", "").strip().lower() == "true":
        return _denied(
            request,
            "local GitHub Actions authority is unavailable inside GitHub "
            "Actions; use the hosted relay",
        )
    if request.function not in _ALLOWED_FUNCTIONS:
        return _denied(
            request,
            f"function {request.function!r} is outside the local GitHub Actions "
            "bootstrap allowlist",
        )
    project = str((request.payload or {}).get("project") or "").strip()
    if not project:
        return _denied(request, "local GitHub Actions request omitted project")
    try:
        from yoke_core.domain import db_helpers
        from yoke_core.domain.project_identity import resolve_project_id

        with db_helpers.connect() as conn:
            project_id = resolve_project_id(conn, project)
    except Exception as exc:
        return _denied(
            request,
            f"could not resolve local GitHub Actions project scope: {exc}",
        )
    actor = request.actor.model_copy(update={"actor_id": DEFAULT_ITEM_ACTOR_ID})
    options = dict(request.options or {})
    options["authorized_project_id"] = project_id
    narrowed = request.model_copy(update={"actor": actor, "options": options})
    from yoke_core.domain.handlers import github_actions_run
    from yoke_core.domain.handlers import github_actions_workflow

    registrations = (
        *github_actions_run.REGISTRATIONS,
        *github_actions_workflow.REGISTRATIONS,
    )
    registration = next(
        row for row in registrations if row["function_id"] == request.function
    )
    outcome = registration["handler"](narrowed)
    return FunctionCallResponse(
        success=outcome.primary_success and outcome.error is None,
        function=request.function,
        version=request.version,
        request_id=request.request_id,
        result=dict(outcome.result_payload),
        warnings=list(outcome.warnings),
        error=outcome.error,
        event_ids=list(outcome.handler_event_ids),
    )


__all__ = ["dispatch"]
