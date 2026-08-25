"""Merge GraphQL transport with one stale installation-token recovery."""

from __future__ import annotations

from datetime import datetime, timezone
import sys
from typing import Any, Callable, Mapping

from yoke_core.domain.gh_rest_transport import (
    RestAuthError,
    RestRequest,
    RestTransportError,
    request_with_retry,
)
from yoke_core.domain.github_app_token_models import utc_now
from yoke_core.domain.project_github_auth import (
    GITHUB_AUTHORITY_INSTALLATION,
    ProjectGithubAuth,
    ProjectGithubAuthError,
    resolve_project_github_auth,
)


clock = utc_now


def graphql_with_auth(
    auth: ProjectGithubAuth,
    *,
    query: str,
    variables: Mapping[str, Any],
    required_permissions: Mapping[str, str],
    request: Callable[..., Any] = request_with_retry,
) -> tuple[dict[str, Any] | None, str | None]:
    """POST one GraphQL document, refreshing a rejected App token once."""
    try:
        response = _request(
            request,
            auth.token,
            query=query,
            variables=variables,
        )
    except RestAuthError as exc:
        if exc.status != 401 or auth.token_source != GITHUB_AUTHORITY_INSTALLATION:
            return None, f"github graphql transport failure: {exc}"
        _log_token_rejection(auth)
        try:
            refreshed = resolve_project_github_auth(
                auth.project,
                required_permissions=required_permissions,
                required_authority=GITHUB_AUTHORITY_INSTALLATION,
                force_refresh=True,
            )
        except ProjectGithubAuthError as refresh_exc:
            return None, (
                f"github graphql installation-token refresh failed: {refresh_exc}"
            )
        if (
            refreshed.repo.casefold() != auth.repo.casefold()
            or refreshed.token_source != GITHUB_AUTHORITY_INSTALLATION
        ):
            return None, (
                "github graphql installation-token refresh changed the "
                "resolved repository authority"
            )
        try:
            response = _request(
                request,
                refreshed.token,
                query=query,
                variables=variables,
            )
        except RestTransportError as retry_exc:
            return None, (
                "github graphql transport failure after installation-token "
                f"refresh: {retry_exc}"
            )
    except RestTransportError as exc:
        return None, f"github graphql transport failure: {exc}"

    body = response.body if isinstance(response.body, dict) else {}
    errors = body.get("errors") or []
    if errors:
        first = errors[0] if isinstance(errors[0], dict) else {}
        message = str(first.get("message") or errors[0])
        return None, f"github graphql refused: {message}"
    data = body.get("data")
    return (data if isinstance(data, dict) else {}), None


def _request(
    request: Callable[..., Any],
    token: str,
    *,
    query: str,
    variables: Mapping[str, Any],
) -> Any:
    return request(
        RestRequest(
            method="POST",
            path="/graphql",
            body={"query": query, "variables": dict(variables)},
            replay_safe=True,
        ),
        token=token,
    )


def _log_token_rejection(auth: ProjectGithubAuth) -> None:
    age = _token_age_seconds(auth.token_issued_at)
    rendered_age = str(age) if age is not None else "unknown"
    print(
        "GitHub GraphQL installation-token rejection "
        f"project={auth.project} status=401 token_age_seconds={rendered_age} "
        "refresh_attempt=1",
        file=sys.stderr,
    )


def _token_age_seconds(issued_at: str) -> int | None:
    raw = str(issued_at or "").strip()
    if not raw:
        return None
    try:
        issued = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if issued.tzinfo is None:
        issued = issued.replace(tzinfo=timezone.utc)
    observed = clock()
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=timezone.utc)
    return max(0, int((observed.astimezone(timezone.utc) - issued).total_seconds()))


__all__ = ["graphql_with_auth"]
