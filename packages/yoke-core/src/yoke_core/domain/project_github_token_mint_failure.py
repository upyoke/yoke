"""Classify a failed GitHub App installation-token mint into its named refusal.

Every project token mint fails through here, so dispatch, readbacks, the
merge queue, and the CI gate all see one answer. GitHub failing (a 5xx, a
rate limit, a network failure or timeout) is :class:`GitHubUnavailable`,
retryable as-is with no repair. GitHub refusing the App or its installation
(401/403/404/422) is :class:`TokenMintFailed` with the repair that status
names. Either way the HTTP status and a short redacted GitHub message travel
in the refusal text, so the recorded evidence says which one happened.
"""

from __future__ import annotations

import json

from yoke_core.domain.gh_rest_http_errors import classify_http_error
from yoke_core.domain.gh_rest_retry_policy import is_retryable_error
from yoke_core.domain.github_app_token_models import (
    GitHubAppTokenError,
    GitHubAppTokenResponseError,
    GitHubAppTokenUnavailableError,
)
from yoke_core.domain.project_github_auth_models import (
    GitHubUnavailable,
    ProjectGithubAuthError,
    TokenMintFailed,
)

_GITHUB_MESSAGE_LIMIT_CHARS = 160

_REPAIR_BY_STATUS = {
    401: (
        "GitHub rejected the App JWT: check the control-plane App issuer, "
        "private-key file, and host clock for project {project}"
    ),
    403: (
        "GitHub refused the App installation: restore the installation "
        "(unsuspend it, re-grant its repository access) for project {project}"
    ),
    404: (
        "GitHub has no such App installation: reconnect GitHub, then re-bind "
        "project {project}"
    ),
    422: (
        "GitHub refused the requested repository or permissions: grant the "
        "App installation the bound repository and approve its permissions "
        "for project {project}"
    ),
}


def token_mint_failure(
    project: str, exc: GitHubAppTokenError
) -> ProjectGithubAuthError:
    """Return the named refusal for one failed installation-token mint."""
    prefix = f"project '{project}' GitHub App token mint failed"
    if isinstance(exc, GitHubAppTokenUnavailableError):
        return GitHubUnavailable(project, f"{prefix}: GitHub is unavailable ({exc})")
    status = exc.status if isinstance(exc, GitHubAppTokenResponseError) else None
    if status is None:
        return TokenMintFailed(project, f"{prefix}: {exc}")
    answer = f"HTTP {status}"
    message = _github_message(exc.body or "")
    if message:
        answer = f"{answer}: {message}"
    if is_retryable_error(classify_http_error(status, exc.body or "", {})):
        return GitHubUnavailable(
            project,
            f"{prefix}: GitHub is unavailable ({answer})",
            http_status=status,
        )
    return TokenMintFailed(
        project,
        f"{prefix}: GitHub refused the request ({answer})",
        http_status=status,
        repair_hint=_REPAIR_BY_STATUS.get(status, ""),
    )


def _github_message(body: str) -> str:
    """GitHub's own error message, or the body's first words, on one line."""
    try:
        payload = json.loads(body)
    except ValueError:
        payload = None
    if isinstance(payload, dict) and isinstance(payload.get("message"), str):
        body = payload["message"]
    text = " ".join(body.split())
    if len(text) > _GITHUB_MESSAGE_LIMIT_CHARS:
        text = text[: _GITHUB_MESSAGE_LIMIT_CHARS - 3].rstrip() + "..."
    return text


__all__ = ["token_mint_failure"]
