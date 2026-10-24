"""List a project's open GitHub issues and open pull requests.

Onboarding asks what work already exists before it proposes new work. The
asking session may hold no GitHub credential of its own, so the read runs
where the project's repository binding is: the control plane, through the
bound App installation token and the bearer-token REST transport.

Both lists are open-only and newest-updated first. GitHub's issues endpoint
also returns pull requests; those entries are dropped from ``issues`` and
served from the pulls endpoint instead. ``truncated`` means the repository
holds open work beyond what this reply carries.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Tuple

from pydantic import BaseModel, Field, ValidationError
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_contracts.github_app_installation_permissions import (
    GITHUB_ISSUES_READ_PERMISSION_LEVELS,
    GITHUB_PULL_REQUESTS_READ_PERMISSION_LEVELS,
)
from yoke_contracts.refusal_recovery import compose_refusal

from yoke_core.domain.handlers.github_actions_set import _auth_failed, _bad_request
from yoke_core.domain.pydantic_validation_safety import safe_validation_message

OWNER_MODULE = "yoke_core.domain.handlers.github_open_work"
FUNCTION_ID = "github.open_work.list"

DEFAULT_LIMIT = 100
MAX_LIMIT = 200
#: GitHub's largest page size for both list endpoints.
PAGE_SIZE = 100
#: Pages read per list. Pull requests reach ``MAX_LIMIT + 1`` within three;
#: the issues endpoint interleaves pull requests, so it may need more pages
#: to collect issues, and stops here with ``truncated`` set.
MAX_PAGES = 5

BINDING_MISSING_CODE = "github_binding_missing"
BINDING_MISSING_RECOVERY = (
    "run `yoke setup` to connect GitHub for this project, or list open work "
    "from the forge yourself"
)

REQUIRED_PERMISSIONS = {
    **GITHUB_ISSUES_READ_PERMISSION_LEVELS,
    **GITHUB_PULL_REQUESTS_READ_PERMISSION_LEVELS,
}


class OpenWorkRequest(BaseModel):
    project: str = Field(..., min_length=1)
    limit: int = Field(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT)


class OpenIssue(BaseModel):
    number: int
    title: str
    labels: List[str]
    updated_at: str
    url: str


class OpenPullRequest(BaseModel):
    number: int
    title: str
    head_ref: str
    draft: bool
    updated_at: str
    url: str


class OpenWorkResponse(BaseModel):
    repo: str
    issues: List[OpenIssue]
    pull_requests: List[OpenPullRequest]
    truncated: bool


def _binding_classes() -> Tuple[type, ...]:
    from yoke_core.domain.project_github_auth import (
        BindingUnavailable,
        InstallationUnavailable,
        MissingCapability,
        MissingInstallation,
        MissingRepoBinding,
        MissingRepoMetadata,
    )

    return (
        BindingUnavailable,
        InstallationUnavailable,
        MissingCapability,
        MissingInstallation,
        MissingRepoBinding,
        MissingRepoMetadata,
    )


def _binding_missing(exc: Exception) -> HandlerOutcome:
    return HandlerOutcome(
        result_payload={},
        primary_success=False,
        error=FunctionError(
            code=BINDING_MISSING_CODE,
            message=compose_refusal(
                f"{getattr(exc, 'code', 'binding')}: {exc}",
                recovery=BINDING_MISSING_RECOVERY,
            ),
        ),
    )


def _rest_failed(exc: Any, repo: str, listing: str, token: str) -> HandlerOutcome:
    from yoke_core.domain.gh_rest_transport import RestAuthError
    from yoke_core.domain.github_response_safety import safe_diagnostic_text

    detail = safe_diagnostic_text(str(exc), secrets=(token,))
    reason = f"listing open {listing} of {repo} failed: {detail}"
    if isinstance(exc, RestAuthError):
        recovery = (
            f"grant the project's GitHub App Issues: read and Pull requests: "
            f"read on {repo}, then retry"
        )
    else:
        recovery = "retry the read once GitHub answers"
    return HandlerOutcome(
        result_payload={},
        primary_success=False,
        error=FunctionError(
            code=getattr(exc, "code", "rest_transport_error"),
            message=compose_refusal(reason, recovery=recovery),
        ),
    )


def _list_open(
    path: str,
    *,
    token: str,
    limit: int,
    row: Callable[[Dict[str, Any]], Any],
) -> Tuple[List[Any], bool]:
    """Collect up to ``limit`` rows, newest-updated first, and whether more exist.

    ``row`` returns ``None`` for an entry this list does not carry.
    """
    from yoke_core.domain.gh_rest_transport import (
        RestRequest,
        RestTransportError,
        request_with_retry,
    )

    rows: List[Any] = []
    for page in range(1, MAX_PAGES + 1):
        response = request_with_retry(
            RestRequest(
                method="GET",
                path=path,
                query={
                    "state": "open",
                    "sort": "updated",
                    "direction": "desc",
                    "per_page": str(PAGE_SIZE),
                    "page": str(page),
                },
            ),
            token=token,
        )
        if not isinstance(response.body, list):
            raise RestTransportError(f"GitHub answered {path} with no list")
        for entry in response.body:
            value = row(entry) if isinstance(entry, dict) else None
            if value is None:
                continue
            rows.append(value)
            if len(rows) > limit:
                return rows[:limit], True
        if len(response.body) < PAGE_SIZE:
            return rows, False
    return rows, True


def _issue_row(entry: Dict[str, Any]) -> OpenIssue | None:
    if "pull_request" in entry:
        return None
    return OpenIssue(
        number=int(entry.get("number") or 0),
        title=str(entry.get("title") or ""),
        labels=[
            str(label.get("name"))
            for label in entry.get("labels") or []
            if isinstance(label, dict) and label.get("name")
        ],
        updated_at=str(entry.get("updated_at") or ""),
        url=str(entry.get("html_url") or ""),
    )


def _pull_row(entry: Dict[str, Any]) -> OpenPullRequest:
    head = entry.get("head") if isinstance(entry.get("head"), dict) else {}
    return OpenPullRequest(
        number=int(entry.get("number") or 0),
        title=str(entry.get("title") or ""),
        head_ref=str(head.get("ref") or ""),
        draft=bool(entry.get("draft")),
        updated_at=str(entry.get("updated_at") or ""),
        url=str(entry.get("html_url") or ""),
    )


def handle_open_work_list(request: FunctionCallRequest) -> HandlerOutcome:
    """Return the bound repository's open issues and open pull requests."""
    if request.target.kind != "global":
        return _bad_request(
            f"target.kind must be 'global' ({FUNCTION_ID} has no item binding)",
            jsonpath="$.target.kind",
        )
    try:
        payload = OpenWorkRequest.model_validate(request.payload or {})
    except ValidationError as exc:
        return _bad_request(safe_validation_message(exc))

    from yoke_core.domain.gh_rest_transport import RestTransportError, split_repo
    from yoke_core.domain.project_github_auth import (
        ProjectGithubAuthError,
        resolve_project_github_auth,
    )

    try:
        resolved = resolve_project_github_auth(
            payload.project, required_permissions=REQUIRED_PERMISSIONS
        )
    except _binding_classes() as exc:
        return _binding_missing(exc)
    except ProjectGithubAuthError as exc:
        return _auth_failed(exc, payload.project)
    repo = str(resolved.repo or "").strip()
    owner, name = split_repo(repo)
    base = f"/repos/{owner}/{name}"
    try:
        issues, issues_more = _list_open(
            f"{base}/issues", token=resolved.token, limit=payload.limit, row=_issue_row
        )
    except RestTransportError as exc:
        return _rest_failed(exc, repo, "issues", resolved.token)
    try:
        pulls, pulls_more = _list_open(
            f"{base}/pulls", token=resolved.token, limit=payload.limit, row=_pull_row
        )
    except RestTransportError as exc:
        return _rest_failed(exc, repo, "pull requests", resolved.token)
    return HandlerOutcome(
        result_payload=OpenWorkResponse(
            repo=repo,
            issues=issues,
            pull_requests=pulls,
            truncated=issues_more or pulls_more,
        ).model_dump(),
        primary_success=True,
    )


REGISTRATIONS = [
    {
        "function_id": FUNCTION_ID,
        "handler": handle_open_work_list,
        "request_model": OpenWorkRequest,
        "response_model": OpenWorkResponse,
        "stability": "stable",
        "owner_module": OWNER_MODULE,
        "target_kinds": ["global"],
        "side_effects": [],
        "emitted_event_names": [],
        "guardrails": ["project_auth_required"],
        "adapter_status": "live",
        "claim_required_kind": None,
        "ambient_session_required": False,
        "minimum_serving_version": "next-release",
    },
]


__all__ = [
    "BINDING_MISSING_CODE",
    "DEFAULT_LIMIT",
    "FUNCTION_ID",
    "MAX_LIMIT",
    "REGISTRATIONS",
    "OpenWorkRequest",
    "OpenWorkResponse",
    "handle_open_work_list",
]
