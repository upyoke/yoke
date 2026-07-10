"""GitHub REST helpers for App-authorized project publishing.

The token is short-lived local GitHub App user authorization. These helpers use
the REST API directly and never require a host ``gh`` binary.
"""

from __future__ import annotations

import urllib.parse
from dataclasses import dataclass
from typing import Any, Mapping

from yoke_cli.config.github_publish_transport import (
    GitHubPublishError,
    request_json as _request_json,
)
from yoke_contracts import github_origin
_USER_PATH = "/user"
_ORGS_PATH = "/user/orgs"
_USER_REPOS_PATH = "/user/repos"
# A repo-create POST whose name collides with an existing repo returns 422
# ("name already exists on this account"); the empty-repo commits probe returns
# 409 ("Git Repository is empty"). Both are recognised by code, not message.
_HTTP_NAME_ALREADY_EXISTS = 422
_HTTP_EMPTY_REPOSITORY = 409
@dataclass(frozen=True)
class RepoOwner:
    """One account a token can create repos under."""

    login: str
    # "user" for the authenticated account, "organization" for an org.
    kind: str


@dataclass(frozen=True)
class RepoRef:
    """One repository the token can reach, for the clone-from-GitHub picker."""

    full_name: str
    clone_url: str
    private: bool


def list_user_repos(
    api_url: str,
    token: str,
    *,
    private_only: bool = False,
    page_size: int = 50,
) -> list[RepoRef]:
    """List repos the token can reach, most-recently-pushed first.

    Hits ``GET /user/repos`` with the same affiliation filter the machine
    verifier uses, so collaborator and org-member repos are included alongside
    the token owner's own. ``private_only`` keeps only private repos (the clone
    picker's private branch). ``page_size`` caps the single page requested so the
    picker never has to paginate; GitHub clamps it to 100.
    """
    page_size = max(1, min(int(page_size), 100))
    payload = _request_json(
        api_url,
        _USER_REPOS_PATH,
        token,
        query={
            "per_page": str(page_size),
            "sort": "pushed",
            "affiliation": "owner,collaborator,organization_member",
        },
    )
    refs: list[RepoRef] = []
    for repo in payload if isinstance(payload, list) else []:
        if not isinstance(repo, Mapping):
            continue
        full_name = repo.get("full_name")
        clone_url = repo.get("clone_url")
        if not (isinstance(full_name, str) and full_name):
            continue
        if not (isinstance(clone_url, str) and clone_url):
            continue
        private = bool(repo.get("private"))
        if private_only and not private:
            continue
        refs.append(RepoRef(full_name=full_name, clone_url=clone_url, private=private))
    return refs


def list_repo_owners(api_url: str, token: str) -> list[RepoOwner]:
    """Return the authenticated user plus every org the token can see.

    The user's own account always leads the list; orgs follow in the order
    GitHub returns them. The owner picker renders these rows verbatim.
    """
    user = _request_json(api_url, _USER_PATH, token)
    if not isinstance(user, Mapping) or not user.get("login"):
        raise GitHubPublishError("GitHub /user response did not include a login")
    owners = [RepoOwner(login=str(user["login"]), kind="user")]
    orgs = _request_json(api_url, _ORGS_PATH, token, query={"per_page": "100"})
    for org in orgs if isinstance(orgs, list) else []:
        if isinstance(org, Mapping) and org.get("login"):
            owners.append(RepoOwner(login=str(org["login"]), kind="organization"))
    return owners


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
        api_url, web_url=web_url, action="repository creation",
    )
    manual_url = endpoint.new_repository_url()
    if not administration_allowed:
        raise GitHubPublishError(
            "Creating repositories through Yoke is an optional GitHub App "
            "Administration permission and is off by default. Create the "
            f"repository at {manual_url}, grant the Yoke GitHub App "
            "access to it, then rerun onboarding; or reconnect the App with "
            "Administration: write to enable one-step creation."
        )
    body: dict[str, Any] = {"name": name, "private": bool(private)}
    if owner == user_login:
        path = _USER_REPOS_PATH
    else:
        path = f"/orgs/{urllib.parse.quote(owner, safe='')}/repos"
    try:
        created = _request_json(api_url, path, token, method="POST", body=body)
    except GitHubPublishError as exc:
        if exc.status == _HTTP_NAME_ALREADY_EXISTS:
            return _reuse_existing_repo(api_url, token, owner=owner, name=name)
        raise
    if not isinstance(created, Mapping) or not created.get("full_name"):
        raise GitHubPublishError(
            "GitHub repo-create response did not include full_name"
        )
    return _repo_summary(created, reused=False)


def _reuse_existing_repo(
    api_url: str,
    token: str,
    *,
    owner: str,
    name: str,
) -> dict[str, Any]:
    """Adopt an existing repo's summary, but only when it is empty.

    Reached when ``create_repo`` got a 422 ("name already exists"). GETs the
    repo and probes its commits: an empty repo (the prior run created it, the
    push had not landed) is our own half-finished work and safe to reuse; a
    populated repo is left untouched with a recovery-shaped error.
    """
    repo_path = (
        f"/repos/{urllib.parse.quote(owner, safe='')}"
        f"/{urllib.parse.quote(name, safe='')}"
    )
    existing = _request_json(api_url, repo_path, token)
    if not isinstance(existing, Mapping) or not existing.get("full_name"):
        raise GitHubPublishError(
            f"a repo named {owner}/{name} already exists but could not be read "
            "to resume — check the name and GitHub App authorization, then re-run"
        )
    if not _repo_is_empty(api_url, token, owner=owner, name=name):
        raise GitHubPublishError(
            f"a repo named {owner}/{name} already exists and has content — pick "
            "a different name, or remove it, to resume"
        )
    return _repo_summary(existing, reused=True)


def _repo_is_empty(
    api_url: str,
    token: str,
    *,
    owner: str,
    name: str,
) -> bool:
    """Return whether ``owner/name`` has no commits.

    ``GET /repos/{owner}/{name}/commits`` answers 409 ("Git Repository is
    empty") for a freshly created repo with no commits, or 200 with an empty
    list; a populated repo returns 200 with at least one commit. Any other
    failure propagates so a transient error is not misread as "empty".
    """
    commits_path = (
        f"/repos/{urllib.parse.quote(owner, safe='')}"
        f"/{urllib.parse.quote(name, safe='')}/commits"
    )
    try:
        commits = _request_json(api_url, commits_path, token)
    except GitHubPublishError as exc:
        if exc.status == _HTTP_EMPTY_REPOSITORY:
            return True
        raise
    return not (isinstance(commits, list) and commits)


def _repo_summary(repo: Mapping[str, Any], *, reused: bool) -> dict[str, Any]:
    """Project a GitHub repo payload onto the summary the push step consumes.

    ``reused`` records whether this repo was freshly created (``False``) or an
    empty existing repo adopted on the 422 resume path (``True``), so the
    onboarding report can read differently after a resumed run.
    """
    return {
        "full_name": str(repo["full_name"]),
        "private": bool(repo.get("private")),
        "clone_url": repo.get("clone_url"),
        "ssh_url": repo.get("ssh_url"),
        "html_url": repo.get("html_url"),
        "default_branch": repo.get("default_branch"),
        "reused": reused,
    }


def fork_repo(
    api_url: str,
    token: str,
    *,
    owner: str,
    repo: str,
    web_url: str = github_origin.DEFAULT_GITHUB_WEB_URL,
) -> dict[str, Any]:
    """Fork ``owner/repo`` into the authenticated account and return its summary.

    Hits ``POST /repos/{owner}/{repo}/forks`` directly so no ``gh`` CLI is
    required, mirroring :func:`create_repo`. GitHub creates the fork under the
    token's own account; the returned dict carries ``full_name``/``clone_url``/
    ``ssh_url``/``default_branch`` for the re-home that follows. GitHub forks are
    eventually consistent, but the create response already names the fork.
    """
    _require_github_com_mutation(
        api_url, web_url=web_url, action="repository forking",
    )
    path = (
        f"/repos/{urllib.parse.quote(owner, safe='')}"
        f"/{urllib.parse.quote(repo, safe='')}/forks"
    )
    created = _request_json(api_url, path, token, method="POST", body={})
    if not isinstance(created, Mapping) or not created.get("full_name"):
        raise GitHubPublishError(
            "GitHub fork response did not include full_name"
        )
    return {
        "full_name": str(created["full_name"]),
        "private": bool(created.get("private")),
        "clone_url": created.get("clone_url"),
        "ssh_url": created.get("ssh_url"),
        "html_url": created.get("html_url"),
        "default_branch": created.get("default_branch"),
    }


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
    "RepoOwner",
    "RepoRef",
    "create_repo",
    "fork_repo",
    "list_repo_owners", "list_user_repos",
]
