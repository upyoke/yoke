"""Create installer proposal pull requests through installation authority.

The installer is the sole consumer. Work-item pull requests belong to the
governed merge command. Repository identity comes from the project binding.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, ValidationError

from yoke_core.domain.handlers.github_actions_set import (
    _auth_failed,
    _bad_request,
    _transport_failed,
)
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    HandlerOutcome,
    FunctionError,
)
from yoke_contracts.github_app_installation_permissions import (
    GITHUB_PULL_REQUESTS_WRITE_PERMISSION_LEVELS,
)
from yoke_contracts.install_proposal import INSTALL_PROPOSAL_BRANCH_PREFIX
from yoke_core.domain.pydantic_validation_safety import safe_validation_message


class PrCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, description="Pull-request title.")
    head: str = Field(
        ...,
        min_length=1,
        description="Branch the changes live on (the PR source branch).",
    )
    base: str = Field(
        "main",
        min_length=1,
        description="Branch the PR merges into (default: main).",
    )
    body: Optional[str] = Field(
        None,
        description="Optional pull-request description (markdown).",
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
        return _bad_request(safe_validation_message(exc))

    if not payload.head.startswith(INSTALL_PROPOSAL_BRANCH_PREFIX):
        return HandlerOutcome(
            result_payload={}, primary_success=False,
            error=FunctionError(
                code="pr_create_not_install_proposal",
                message="Only installer proposal branches may use this function; "
                "open a work item pull request with `yoke merge PREFIX-N`.",
            ),
        )

    from yoke_core.domain.project_github_auth import (
        GITHUB_AUTHORITY_INSTALLATION,
        ProjectGithubAuthError,
        resolve_project_github_auth,
    )

    try:
        resolved = resolve_project_github_auth(
            payload.project,
            required_permissions=GITHUB_PULL_REQUESTS_WRITE_PERMISSION_LEVELS,
            required_authority=GITHUB_AUTHORITY_INSTALLATION,
        )
    except ProjectGithubAuthError as exc:
        return _auth_failed(exc, payload.project)

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
        "adapter_status": "internal",
        "claim_required_kind": None,
    },
]


__all__ = [
    "PrCreateRequest",
    "PrCreateResponse",
    "REGISTRATIONS",
    "handle_pr_create",
]
