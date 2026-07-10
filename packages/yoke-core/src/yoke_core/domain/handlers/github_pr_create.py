"""Handler for ``github.pr.create`` — open a pull request via bearer-token REST.

First member of the repo-level ``github.*`` family (PRs are repo
surfaces, not Actions surfaces, so this deliberately does not overload
``github_actions.*``). PR-create otherwise has only the generic
:mod:`yoke_core.domain.gh_rest_transport`, which would push agents back
to the host ``gh`` binary Yoke is otherwise free of.

Owner/repo resolve from the project's verified GitHub App repo binding through
``resolve_project_github_auth``, the same resolver the ``github_actions.*``
handlers use; the payload never carries a repo slug. The POST routes
through :func:`yoke_core.domain.github_pr_rest.create_pull_request`.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, ValidationError

from yoke_core.domain.handlers.github_actions_set import (
    _auth_failed,
    _bad_request,
    _sanitized_validation_message,
    _transport_failed,
)
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    HandlerOutcome,
)
from yoke_contracts.github_app_installation_permissions import (
    GITHUB_PULL_REQUESTS_WRITE_PERMISSION_LEVELS,
)


class PrCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, description="Pull-request title.")
    head: str = Field(
        ..., min_length=1,
        description="Branch the changes live on (the PR source branch).",
    )
    base: str = Field(
        "main",
        min_length=1,
        description="Branch the PR merges into (default: main).",
    )
    body: Optional[str] = Field(
        None, description="Optional pull-request description (markdown).",
    )
    draft: bool = Field(False, description="Open the PR as a draft.")
    project: str = Field(
        ...,
        min_length=1,
        description="Project capability owning the GitHub repo binding.",
    )


class PrCreateResponse(BaseModel):
    number: int
    url: str


def handle_pr_create(request: FunctionCallRequest) -> HandlerOutcome:
    if request.target.kind != "global":
        return _bad_request(
            "target.kind must be 'global' (github.pr.create has no item binding)",
            jsonpath="$.target.kind",
        )

    try:
        payload = PrCreateRequest.model_validate(request.payload or {})
    except ValidationError as exc:
        return _bad_request(_sanitized_validation_message(exc))

    from yoke_core.domain.project_github_auth import (
        ProjectGithubAuthError,
        repair_command_hint,
        resolve_project_github_auth,
    )

    try:
        resolved = resolve_project_github_auth(
            payload.project,
            required_permissions=GITHUB_PULL_REQUESTS_WRITE_PERMISSION_LEVELS,
        )
    except ProjectGithubAuthError as exc:
        return _auth_failed(
            f"{exc.code}: {exc}",
            repair_hint=repair_command_hint(exc, payload.project),
        )

    from yoke_core.domain import github_pr_rest
    from yoke_core.domain.gh_rest_transport import RestTransportError

    try:
        created = github_pr_rest.create_pull_request(
            resolved.repo,
            title=payload.title,
            head=payload.head,
            base=payload.base,
            body=payload.body,
            draft=payload.draft,
            token=resolved.token,
        )
    except RestTransportError as exc:
        return _transport_failed(f"create_pull_request failed: {exc}")

    response = PrCreateResponse(number=created["number"], url=created["url"])
    return HandlerOutcome(
        result_payload=response.model_dump(),
        primary_success=True,
    )


REGISTRATIONS: List[Dict[str, Any]] = [
    {
        "function_id": "github.pr.create",
        "handler": handle_pr_create,
        "request_model": PrCreateRequest,
        "response_model": PrCreateResponse,
        "stability": "stable",
        "owner_module": "yoke_core.domain.handlers.github_pr_create",
        "target_kinds": ["global"],
        "side_effects": ["github_pr_create"],
        "emitted_event_names": [],
        "guardrails": ["project_auth_required"],
        "adapter_status": "live",
        "claim_required_kind": None,
    },
]


__all__ = [
    "PrCreateRequest",
    "PrCreateResponse",
    "REGISTRATIONS",
    "handle_pr_create",
]
