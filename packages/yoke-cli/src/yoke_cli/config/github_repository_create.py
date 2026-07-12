"""Identity- and visibility-bound GitHub repository creation/resume."""

from __future__ import annotations

from typing import Any, Callable, Mapping
import urllib.parse

from yoke_cli.config.github_publish_transport import GitHubPublishError
from yoke_cli.config import github_repository_name


HTTP_NAME_ALREADY_EXISTS = 422
HTTP_EMPTY_REPOSITORY = 409
REPOSITORY_CONTENT_MISMATCH = (
    "already has content that does not match this checkout"
)


def create_repository(
    request_json: Callable[..., Any],
    api_url: str,
    token: str,
    *,
    owner: str,
    name: str,
    user_login: str,
    private: bool,
    administration_allowed: bool,
    manual_url: str,
) -> dict[str, Any]:
    """Create exactly one requested repo or adopt its empty prior-run shell."""

    try:
        name = github_repository_name.validated(name)
    except github_repository_name.GitHubRepositoryNameError as exc:
        raise GitHubPublishError(str(exc)) from exc

    if not administration_allowed:
        raise GitHubPublishError(
            "Creating repositories through Yoke is an optional GitHub App "
            "Administration permission and is off by default. Create the "
            f"repository at {manual_url}, grant the Yoke GitHub App "
            "access to it, then rerun onboarding. One-step creation requires "
            "an App operator to add Administration: write to the App "
            "registration and the installation owner to approve that change; "
            "reconnecting alone does not change the App's permissions."
        )
    body: dict[str, Any] = {"name": name, "private": bool(private)}
    path = (
        "/user/repos"
        if owner.casefold() == user_login.casefold()
        else f"/orgs/{urllib.parse.quote(owner, safe='')}/repos"
    )
    try:
        created = request_json(
            api_url, path, token, method="POST", body=body,
        )
    except GitHubPublishError as exc:
        if exc.status != HTTP_NAME_ALREADY_EXISTS:
            raise
        return verify_resumable_repository(
            request_json, api_url, token,
            owner=owner, name=name, private=private,
            expected_head_sha=None,
        )
    verify_repository(created, owner=owner, name=name, private=private)
    return repository_summary(created, reused=False)


def verify_resumable_repository(
    request_json: Callable[..., Any],
    api_url: str,
    token: str,
    *,
    owner: str,
    name: str,
    private: bool,
    expected_head_sha: str | None,
) -> dict[str, Any]:
    """Live-verify a prior-run repo and any existing default-branch content."""

    repo_path = _repo_path(owner, name)
    existing = request_json(api_url, repo_path, token)
    if not isinstance(existing, Mapping) or not existing.get("full_name"):
        raise GitHubPublishError(
            f"a repo named {owner}/{name} exists but could not be verified "
            "for resume; check GitHub App authorization and retry"
        )
    verify_repository(existing, owner=owner, name=name, private=private)
    commits = repository_commits(
        request_json, api_url, token, owner=owner, name=name,
    )
    if commits:
        first = commits[0] if isinstance(commits[0], Mapping) else {}
        remote_head = str(first.get("sha") or "")
        if not expected_head_sha or remote_head != expected_head_sha:
            raise GitHubPublishError(
                f"a repo named {owner}/{name} {REPOSITORY_CONTENT_MISMATCH}; "
                "no push was attempted"
            )
    return repository_summary(existing, reused=True)


def verify_existing_repository(
    request_json: Callable[..., Any],
    api_url: str,
    token: str,
    *,
    owner: str,
    name: str,
    expected_head_sha: str,
    private: bool,
    repository_id: int,
) -> dict[str, Any]:
    """Verify an explicitly selected existing repo before attaching/pushing."""

    try:
        name = github_repository_name.validated(name)
    except github_repository_name.GitHubRepositoryNameError as exc:
        raise GitHubPublishError(str(exc)) from exc
    existing = request_json(api_url, _repo_path(owner, name), token)
    expected = f"{owner}/{name}"
    full_name = str(existing.get("full_name") or "") if isinstance(
        existing, Mapping
    ) else ""
    permissions = existing.get("permissions") if isinstance(
        existing, Mapping
    ) else None
    actual_private = existing.get("private") if isinstance(existing, Mapping) else None
    actual_id = existing.get("id") if isinstance(existing, Mapping) else None
    if full_name.casefold() != expected.casefold():
        raise GitHubPublishError(
            "GitHub returned a different repository than the one selected; "
            "no remote was changed"
        )
    if actual_id != repository_id:
        raise GitHubPublishError(
            "The selected GitHub repository identity changed; no remote was changed"
        )
    if actual_private is not private:
        visibility = "private" if private else "public"
        raise GitHubPublishError(
            f"{expected} is not the selected {visibility} repository; no remote "
            "was changed"
        )
    if not isinstance(permissions, Mapping) or permissions.get("push") is not True:
        raise GitHubPublishError(
            f"GitHub authorization cannot push to {expected}; no remote was changed"
        )
    commits = repository_commits(
        request_json, api_url, token, owner=owner, name=name,
    )
    if commits:
        first = commits[0] if isinstance(commits[0], Mapping) else {}
        if str(first.get("sha") or "") != expected_head_sha:
            raise GitHubPublishError(
                f"{expected} {REPOSITORY_CONTENT_MISMATCH}; no push was attempted"
            )
    return repository_summary(existing, reused=True)


def repository_commits(
    request_json: Callable[..., Any],
    api_url: str,
    token: str,
    *,
    owner: str,
    name: str,
) -> list[Any]:
    """Return a validated commits list, mapping GitHub's empty-repo 409 to []."""

    try:
        commits = request_json(
            api_url, f"{_repo_path(owner, name)}/commits", token,
        )
    except GitHubPublishError as exc:
        if exc.status == HTTP_EMPTY_REPOSITORY:
            return []
        raise
    if not isinstance(commits, list):
        raise GitHubPublishError(
            "GitHub commits response did not contain a list; the existing "
            "repository will not be reused"
        )
    return commits


def verify_repository(
    candidate: Any,
    *,
    owner: str,
    name: str,
    private: bool,
) -> None:
    expected = f"{owner}/{name}"
    full_name = str(candidate.get("full_name") or "") if isinstance(
        candidate, Mapping
    ) else ""
    visibility = candidate.get("private") if isinstance(candidate, Mapping) else None
    if (
        full_name.casefold() != expected.casefold()
        or visibility is not bool(private)
    ):
        raise GitHubPublishError(
            "GitHub repository response did not match the requested owner, "
            "name, and visibility; no push was attempted"
        )


def repository_summary(
    repo: Mapping[str, Any], *, reused: bool,
) -> dict[str, Any]:
    return {
        "full_name": str(repo["full_name"]),
        "private": bool(repo.get("private")),
        "clone_url": repo.get("clone_url"),
        "ssh_url": repo.get("ssh_url"),
        "html_url": repo.get("html_url"),
        "default_branch": repo.get("default_branch"),
        "reused": reused,
    }


def _repo_path(owner: str, name: str) -> str:
    return (
        f"/repos/{urllib.parse.quote(owner, safe='')}"
        f"/{urllib.parse.quote(name, safe='')}"
    )


__all__ = [
    "create_repository",
    "repository_summary",
    "verify_repository",
    "verify_existing_repository",
    "verify_resumable_repository",
]
