"""Explicit item and epic-task GitHub link repair without remote writes."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_core.domain import db_backend, db_helpers, github_rest
from yoke_core.domain.backlog_github_fetch import _item_context
from yoke_core.domain.project_github_auth import ProjectGithubAuthError


class GithubLinkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    issue_number: int | None = Field(default=None, gt=0, strict=True)
    task_num: int | None = Field(default=None, gt=0, strict=True)


class GithubLinkResponse(BaseModel):
    item_id: int
    task_num: int | None
    previous_issue: str
    github_issue: str
    changed: bool


def _error(code: str, message: str) -> HandlerOutcome:
    return HandlerOutcome(
        result_payload={},
        primary_success=False,
        error=FunctionError(code=code, message=message),
    )


def handle_github_link(request: FunctionCallRequest) -> HandlerOutcome:
    if request.target.kind != "item" or request.target.item_id is None:
        return _error("invalid_payload", "Name an item with public_ref (PREFIX-N).")
    try:
        payload = GithubLinkRequest.model_validate(request.payload or {})
    except ValueError as exc:
        return _error(
            "invalid_payload", f"{exc}. Use a positive issue/task number or --unlink."
        )
    item_id = int(request.target.item_id)
    with db_helpers.connect() as conn:
        context = _item_context(item_id, conn=conn)
        if context is None:
            return _error(
                "item_not_found",
                "Read the item reference and retry with an existing item.",
            )
        _, project, _repo = context
        p = "%s" if db_backend.connection_is_postgres(conn) else "?"
        table = "epic_tasks" if payload.task_num is not None else "items"
        where = (
            f"epic_id = {p} AND task_num = {p}"
            if payload.task_num is not None
            else f"id = {p}"
        )
        params = (
            (item_id, payload.task_num) if payload.task_num is not None else (item_id,)
        )
        row = conn.execute(
            f"SELECT github_issue FROM {table} WHERE {where} FOR UPDATE", params
        ).fetchone()
        if row is None:
            return _error(
                "task_not_found",
                "Read the epic task list and retry with an existing task number.",
            )
        previous = str(row[0] or "")
        if payload.issue_number is not None:
            try:
                issue = github_rest.get_issue(
                    project=project, number=payload.issue_number
                )
            except (ProjectGithubAuthError, github_rest.RestTransportError) as exc:
                return _error(
                    "github_issue_unverified",
                    f"{exc}. Check GitHub access with yoke github status, then retry; the link is unchanged.",
                )
            if issue is None or issue.is_pull_request:
                return _error(
                    "github_issue_not_found",
                    "Choose an issue in the project's bound repository, then retry; pull requests cannot be linked.",
                )
        linked = f"#{payload.issue_number}" if payload.issue_number is not None else ""
        if previous != linked:
            conn.execute(
                f"UPDATE {table} SET github_issue = {p} WHERE {where}",
                (linked, *params),
            )
            if payload.task_num is None:
                conn.execute(
                    f"UPDATE items SET github_body_compact_pending = NULL WHERE id = {p}",
                    (item_id,),
                )
            conn.commit()
    return HandlerOutcome(
        primary_success=True,
        result_payload=GithubLinkResponse(
            item_id=item_id,
            task_num=payload.task_num,
            previous_issue=previous,
            github_issue=linked,
            changed=previous != linked,
        ).model_dump(),
    )


REGISTRATIONS = [
    {
        "function_id": "items.github_link",
        "handler": handle_github_link,
        "request_model": GithubLinkRequest,
        "response_model": GithubLinkResponse,
        "stability": "stable",
        "owner_module": "yoke_core.domain.handlers.items_github_link",
        "target_kinds": ["item"],
        "side_effects": ["update_github_link"],
        "guardrails": ["claim_required", "project_github_issue_verified"],
        "adapter_status": "live",
        "claim_required_kind": "item",
        "minimum_serving_version": "next-release",
    }
]
