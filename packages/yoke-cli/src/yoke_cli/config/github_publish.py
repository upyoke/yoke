"""GitHub REST helpers for publishing a project to a new repo.

Onboarding's "Also publish to GitHub?" step needs two GitHub writes that the
read-only verification helper (:mod:`github_machine_verify`) does not cover:
listing the accounts a token can create repos under, and creating a repo. Both
live behind the small functions here so the wizard and ``project_onboard`` can
drive them while tests mock the network at one seam.

The token is the machine GitHub PAT the Connect step already connected, so no
``gh`` CLI prerequisite is introduced — the REST API is hit directly.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Mapping

_TIMEOUT_S = 20.0
_USER_PATH = "/user"
_ORGS_PATH = "/user/orgs"
_USER_REPOS_PATH = "/user/repos"
# A repo-create POST whose name collides with an existing repo returns 422
# ("name already exists on this account"); the empty-repo commits probe returns
# 409 ("Git Repository is empty"). Both are recognised by code, not message.
_HTTP_NAME_ALREADY_EXISTS = 422
_HTTP_EMPTY_REPOSITORY = 409


class GitHubPublishError(RuntimeError):
    """A GitHub publish REST call failed.

    ``status`` carries the HTTP status code when the failure was a non-2xx REST
    response (set by :func:`_request_json` where it wraps an
    :class:`urllib.error.HTTPError`); it is ``None`` for transport/parse
    failures. Callers branch on it to recognise a specific status — e.g.
    :func:`create_repo` treats a ``422`` as "name already exists" and resumes —
    without re-parsing the message string.
    """

    def __init__(self, *args: Any, status: int | None = None) -> None:
        super().__init__(*args)
        self.status = status


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
) -> dict[str, Any]:
    """Create a repo under ``owner`` and return its summary.

    The endpoint differs by owner kind: the authenticated user's own repos go
    to ``POST /user/repos``; an org's repos go to ``POST /orgs/{org}/repos``.
    The repo is private by default. The returned dict carries ``full_name``,
    ``clone_url``/``ssh_url``, and ``default_branch`` for the push that follows.

    Idempotent on a resume: when the create POST fails because the name already
    exists (HTTP 422) AND the pre-existing repo is empty (no commits — our prior
    run created it but the push had not landed yet), the existing repo is reused
    and its summary returned in the same shape, so the idempotent re-home can
    re-push and complete. A pre-existing repo that already has content is NOT
    adopted — it raises a recovery-shaped error rather than risk pushing into a
    populated repo the caller did not mean to publish over.

    The returned summary carries ``reused``: ``False`` on a fresh create, ``True``
    on the 422 resume path, so the caller can tell the user the repo already
    existed and was reused rather than freshly created this run.
    """
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
            "to resume — check the name and your GitHub token, then re-run"
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
) -> dict[str, Any]:
    """Fork ``owner/repo`` into the authenticated account and return its summary.

    Hits ``POST /repos/{owner}/{repo}/forks`` directly so no ``gh`` CLI is
    required, mirroring :func:`create_repo`. GitHub creates the fork under the
    token's own account; the returned dict carries ``full_name``/``clone_url``/
    ``ssh_url``/``default_branch`` for the re-home that follows. GitHub forks are
    eventually consistent, but the create response already names the fork.
    """
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


def _request_json(
    api_url: str,
    path: str,
    token: str,
    *,
    method: str = "GET",
    query: Mapping[str, str] | None = None,
    body: Mapping[str, Any] | None = None,
) -> Any:
    url = api_url.rstrip("/") + path
    if query:
        url = url + "?" + urllib.parse.urlencode(query)
    data = json.dumps(dict(body)).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = _error_detail(exc)
        raise GitHubPublishError(
            f"GitHub call failed: {method} {url} returned HTTP {exc.code}"
            + (f" — {detail}" if detail else ""),
            status=exc.code,
        ) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise GitHubPublishError(
            f"GitHub call failed against {url}: {exc}"
        ) from exc
    try:
        return json.loads(raw) if raw else None
    except ValueError as exc:
        raise GitHubPublishError(
            f"GitHub call returned invalid JSON from {url}"
        ) from exc


def _error_detail(exc: urllib.error.HTTPError) -> str:
    try:
        payload = json.loads(exc.read().decode("utf-8"))
    except (ValueError, OSError):
        return ""
    if isinstance(payload, Mapping) and payload.get("message"):
        return str(payload["message"])
    return ""


__all__ = [
    "GitHubPublishError",
    "RepoOwner",
    "RepoRef",
    "create_repo",
    "fork_repo",
    "list_repo_owners",
    "list_user_repos",
]
