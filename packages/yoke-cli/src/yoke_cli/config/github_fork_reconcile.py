"""Identity-bound reconciliation for ambiguous GitHub fork creation."""

from __future__ import annotations

import time
from typing import Any, Callable, Mapping
import urllib.parse

from yoke_cli.config.github_publish_transport import GitHubPublishError


FORK_RECONCILE_DELAYS_SECONDS = (0.0, 1.0, 2.0, 4.0, 8.0)
FORK_RECONCILE_DEADLINE_SECONDS = 15.0


def existing_fork(
    request_json: Callable[..., Any],
    api_url: str,
    token: str,
    *,
    source_owner: str,
    source_repo: str,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    deadline: float | None = None,
    authenticated_login: str | None = None,
) -> Mapping[str, Any]:
    """Find only the authenticated user's exact fork of the requested source."""
    selected_deadline = deadline or (
        monotonic() + FORK_RECONCILE_DEADLINE_SECONDS
    )
    login = str(authenticated_login or "").strip()
    if not login:
        user = request_json(
            api_url, "/user", token,
            deadline=selected_deadline, monotonic=monotonic,
        )
        _require_time(selected_deadline, monotonic)
        if not isinstance(user, Mapping) or not user.get("login"):
            raise GitHubPublishError(
                "GitHub fork reconciliation could not identify the authenticated user"
            )
        login = str(user["login"])
    expected_name = f"{login}/{source_repo}"
    path = (
        f"/repos/{urllib.parse.quote(login, safe='')}"
        f"/{urllib.parse.quote(source_repo, safe='')}"
    )
    last_error: GitHubPublishError | None = None
    for delay in FORK_RECONCILE_DELAYS_SECONDS:
        if delay:
            remaining = selected_deadline - monotonic()
            if remaining <= 0:
                break
            sleep(min(delay, remaining))
            if selected_deadline - monotonic() <= 0:
                break
        try:
            candidate = request_json(
                api_url, path, token,
                deadline=selected_deadline, monotonic=monotonic,
            )
            if selected_deadline - monotonic() <= 0:
                break
        except GitHubPublishError as exc:
            if exc.status != 404:
                raise
            last_error = exc
            continue
        verify_fork(
            candidate,
            expected_name=expected_name,
            source_name=f"{source_owner}/{source_repo}",
        )
        return candidate
    raise GitHubPublishError(
        "GitHub fork creation had an ambiguous response and the exact fork "
        "did not become readable before the reconciliation deadline"
    ) from last_error


def _require_time(
    deadline: float, monotonic: Callable[[], float],
) -> None:
    if deadline - monotonic() <= 0:
        raise GitHubPublishError(
            "GitHub fork reconciliation exceeded its operation deadline"
        )


def verify_fork(
    candidate: Any,
    *,
    expected_name: str,
    source_name: str,
) -> None:
    parent = candidate.get("parent") if isinstance(candidate, Mapping) else None
    full_name = str(candidate.get("full_name") or "") if isinstance(
        candidate, Mapping
    ) else ""
    parent_name = str(parent.get("full_name") or "") if isinstance(
        parent, Mapping
    ) else ""
    candidate_private = candidate.get("private") if isinstance(
        candidate, Mapping
    ) else None
    is_fork = candidate.get("fork") if isinstance(candidate, Mapping) else None
    parent_private = (
        parent.get("private") if isinstance(parent, Mapping) else None
    )
    if (
        full_name.casefold() != expected_name.casefold()
        or is_fork is not True
        or parent_name.casefold() != source_name.casefold()
        or not isinstance(candidate_private, bool)
        or not isinstance(parent_private, bool)
        or candidate_private is not parent_private
    ):
        raise GitHubPublishError(
            "an existing repository occupies the expected fork name but is not "
            "the exact fork of the requested source; no remote was changed"
        )


__all__ = [
    "FORK_RECONCILE_DEADLINE_SECONDS",
    "FORK_RECONCILE_DELAYS_SECONDS",
    "existing_fork",
    "verify_fork",
]
