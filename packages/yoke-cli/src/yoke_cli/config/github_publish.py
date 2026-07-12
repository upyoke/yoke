"""GitHub REST helpers for App-authorized project publishing.

The token is short-lived local GitHub App user authorization. These helpers use
the REST API directly and never require a host ``gh`` binary.
"""

from __future__ import annotations

import time
import urllib.parse
from typing import Any, Mapping

from yoke_cli.config import github_fork_reconcile
from yoke_cli.config import github_publish_repositories
from yoke_cli.config import github_repository_create
from yoke_cli.config.github_publish_repositories import (
    OWNER_LIST_DEADLINE_SECONDS,
    RepoOwner,
    RepoRef,
)
from yoke_cli.config.github_publish_transport import (
    GitHubPublishError,
    request_json as _request_json,
)
from yoke_contracts import github_origin

_USER_PATH = "/user"


def list_user_repos(
    api_url: str,
    token: str,
    *,
    private_only: bool = False,
    page_size: int = 50,
    web_url: str = github_origin.DEFAULT_GITHUB_WEB_URL,
    monotonic=time.monotonic,
) -> list[RepoRef]:
    """List repos the token can reach, most-recently-pushed first.

    Hits ``GET /user/repos`` with the same affiliation filter the machine
    verifier uses, so collaborator and org-member repos are included alongside
    the token owner's own. ``private_only`` keeps only private repos (the clone
    picker's private branch). Results are paginated under one bounded operation
    deadline; GitHub clamps ``page_size`` to 100.
    """
    return github_publish_repositories.list_user_repos(
        _request_json,
        api_url,
        token,
        private_only=private_only,
        page_size=page_size,
        web_url=web_url,
        monotonic=monotonic,
    )


def list_repo_owners(
    api_url: str,
    token: str,
    *,
    monotonic=time.monotonic,
) -> list[RepoOwner]:
    """Return the authenticated user plus every org the token can see.

    The user's own account always leads the list; orgs follow in the order
    GitHub returns them. The owner picker renders these rows verbatim.
    """
    return github_publish_repositories.list_repo_owners(
        _request_json,
        api_url,
        token,
        monotonic=monotonic,
    )


def create_repo(
    api_url: str,
    token: str,
    *,
    owner: str,
    name: str,
    user_login: str,
    private: bool = True,
    administration_allowed: bool = False,
    web_url: str = github_origin.DEFAULT_GITHUB_WEB_URL,
) -> dict[str, Any]:
    """Create a repo, safely resuming only a prior empty-repo create."""
    endpoint = _require_github_com_mutation(
        api_url,
        web_url=web_url,
        action="repository creation",
    )
    return github_repository_create.create_repository(
        _request_json,
        api_url,
        token,
        owner=owner,
        name=name,
        user_login=user_login,
        private=private,
        administration_allowed=administration_allowed,
        manual_url=endpoint.new_repository_url(),
    )


def verify_resumable_repo(
    api_url: str,
    token: str,
    *,
    owner: str,
    name: str,
    private: bool,
    expected_head_sha: str,
    web_url: str = github_origin.DEFAULT_GITHUB_WEB_URL,
) -> dict[str, Any]:
    """Live-verify a prior-run repo before an idempotent resumed push."""

    _require_github_com_mutation(
        api_url,
        web_url=web_url,
        action="repository resume",
    )
    return github_repository_create.verify_resumable_repository(
        _request_json,
        api_url,
        token,
        owner=owner,
        name=name,
        private=private,
        expected_head_sha=expected_head_sha,
    )


def verify_existing_repo(
    api_url: str,
    token: str,
    *,
    owner: str,
    name: str,
    expected_head_sha: str,
    private: bool,
    repository_id: int,
    web_url: str = github_origin.DEFAULT_GITHUB_WEB_URL,
) -> dict[str, Any]:
    """Live-verify one manually selected App-visible repository."""

    # Manual attachment does not mutate through the REST API. It verifies the
    # exact App-visible repository before the later authenticated Git push, so
    # it is valid for both GitHub.com and a configured GitHub Enterprise host.
    try:
        github_origin.validate_github_endpoint_pair(api_url, web_url)
    except github_origin.GitHubApiOriginError as exc:
        raise GitHubPublishError(str(exc)) from exc
    return github_repository_create.verify_existing_repository(
        _request_json,
        api_url,
        token,
        owner=owner,
        name=name,
        expected_head_sha=expected_head_sha,
        private=private,
        repository_id=repository_id,
    )


def verify_resumable_fork(
    api_url: str,
    token: str,
    *,
    source_owner: str,
    source_repo: str,
    candidate_full_name: str,
    web_url: str = github_origin.DEFAULT_GITHUB_WEB_URL,
) -> dict[str, Any]:
    """Live-verify a locally remembered fork against user, parent, and privacy."""

    _require_github_com_mutation(
        api_url,
        web_url=web_url,
        action="fork resume",
    )
    user = _request_json(api_url, _USER_PATH, token)
    login = str(user.get("login") or "") if isinstance(user, Mapping) else ""
    expected = f"{login}/{source_repo}"
    if not login or candidate_full_name.casefold() != expected.casefold():
        raise GitHubPublishError(
            "the locally remembered fork does not belong to the authenticated "
            "user; no remote was changed"
        )
    candidate = _request_json(
        api_url,
        f"/repos/{urllib.parse.quote(login, safe='')}"
        f"/{urllib.parse.quote(source_repo, safe='')}",
        token,
    )
    github_fork_reconcile.verify_fork(
        candidate,
        expected_name=expected,
        source_name=f"{source_owner}/{source_repo}",
    )
    return github_repository_create.repository_summary(candidate, reused=True)


def fork_repo(
    api_url: str,
    token: str,
    *,
    owner: str,
    repo: str,
    web_url: str = github_origin.DEFAULT_GITHUB_WEB_URL,
    sleep=time.sleep,
    monotonic=time.monotonic,
) -> dict[str, Any]:
    """Fork ``owner/repo`` into the authenticated account and return its summary.

    Hits ``POST /repos/{owner}/{repo}/forks`` directly so no ``gh`` CLI is
    required, mirroring :func:`create_repo`. GitHub creates the fork under the
    token's own account; the returned dict carries ``full_name``/``clone_url``/
    ``ssh_url``/``default_branch`` for the re-home that follows. GitHub forks are
    eventually consistent, but the create response already names the fork.
    """
    _require_github_com_mutation(
        api_url,
        web_url=web_url,
        action="repository forking",
    )
    deadline = monotonic() + (github_fork_reconcile.FORK_RECONCILE_DEADLINE_SECONDS)
    user = _request_json(
        api_url,
        _USER_PATH,
        token,
        deadline=deadline,
        monotonic=monotonic,
    )
    if not isinstance(user, Mapping) or not user.get("login"):
        raise GitHubPublishError(
            "GitHub fork creation could not identify the authenticated user"
        )
    login = str(user["login"])
    path = (
        f"/repos/{urllib.parse.quote(owner, safe='')}"
        f"/{urllib.parse.quote(repo, safe='')}/forks"
    )
    try:
        created = _request_json(
            api_url,
            path,
            token,
            method="POST",
            body={},
            deadline=deadline,
            monotonic=monotonic,
        )
        reused = False
    except GitHubPublishError as exc:
        if exc.status not in (
            None,
            github_repository_create.HTTP_NAME_ALREADY_EXISTS,
        ):
            raise
        created = github_fork_reconcile.existing_fork(
            _request_json,
            api_url,
            token,
            source_owner=owner,
            source_repo=repo,
            sleep=sleep,
            monotonic=monotonic,
            deadline=deadline,
            authenticated_login=login,
        )
        reused = True
    github_fork_reconcile.verify_fork(
        created,
        expected_name=f"{login}/{repo}",
        source_name=f"{owner}/{repo}",
    )
    return github_repository_create.repository_summary(created, reused=reused)


def _require_github_com_mutation(
    api_url: str,
    *,
    action: str,
    web_url: str = github_origin.DEFAULT_GITHUB_WEB_URL,
) -> github_origin.GitHubEndpointPair:
    endpoint = github_origin.validate_github_endpoint_pair(api_url, web_url)
    if endpoint.deployment_kind != "github_cloud":
        raise GitHubPublishError(
            f"One-step {action} currently supports GitHub.com only. Complete "
            f"that action at {endpoint.new_repository_url()}, grant the App "
            "access, then refresh onboarding."
        )
    return endpoint


__all__ = [
    "GitHubPublishError",
    "OWNER_LIST_DEADLINE_SECONDS",
    "RepoOwner",
    "RepoRef",
    "create_repo",
    "fork_repo",
    "list_repo_owners",
    "list_user_repos",
    "verify_resumable_fork",
    "verify_resumable_repo",
    "verify_existing_repo",
]
