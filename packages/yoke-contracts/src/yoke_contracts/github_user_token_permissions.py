"""Shared GitHub user-token permission contract for Yoke machine onboarding."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

ACCESS_READ = "read"
ACCESS_WRITE = "write"


@dataclass(frozen=True)
class GitHubUserTokenPermission:
    """One repository permission Yoke needs from a GitHub user token."""

    key: str
    label: str
    access: str


@dataclass(frozen=True)
class GitHubUserTokenReadProbe:
    """A non-mutating API check for one repository permission."""

    key: str
    path_template: str | None
    query: Mapping[str, str] | None = None
    needs_existing_environment: bool = False
    unavailable_reason: str = ""


REQUIRED_REPOSITORY_USER_TOKEN_PERMISSIONS = (
    GitHubUserTokenPermission("actions", "Actions", ACCESS_WRITE),
    GitHubUserTokenPermission("administration", "Administration", ACCESS_WRITE),
    GitHubUserTokenPermission("contents", "Contents", ACCESS_WRITE),
    GitHubUserTokenPermission("environments", "Environments", ACCESS_WRITE),
    GitHubUserTokenPermission("issues", "Issues", ACCESS_WRITE),
    GitHubUserTokenPermission("metadata", "Metadata", ACCESS_READ),
    GitHubUserTokenPermission("pull_requests", "Pull requests", ACCESS_WRITE),
    GitHubUserTokenPermission("secrets", "Secrets", ACCESS_WRITE),
    GitHubUserTokenPermission("variables", "Variables", ACCESS_WRITE),
    GitHubUserTokenPermission("workflows", "Workflows", ACCESS_WRITE),
)

# Scope-bearing tokens do not expose per-repository permission names. GitHub
# reports those grants through X-OAuth-Scopes; repo covers private repository
# read/write APIs and workflow is required for workflow file/API access.
REQUIRED_SCOPED_USER_TOKEN_SCOPES = ("repo", "workflow")

# Scopes that grant repository creation. `repo` covers private + public create;
# `public_repo` covers public-only create. Repository-scoped user tokens expose
# no create grant via API, so they are classified UNKNOWN, never True/False.
CREATE_REPO_SCOPE_PRIVATE = "repo"
CREATE_REPO_SCOPE_PUBLIC = "public_repo"

NON_MUTATING_REPOSITORY_USER_TOKEN_READ_PROBES = {
    "actions": GitHubUserTokenReadProbe(
        "actions",
        "/repos/{owner}/{repo}/actions/runs",
        {"per_page": "1"},
    ),
    "administration": GitHubUserTokenReadProbe(
        "administration",
        "/repos/{owner}/{repo}/actions/permissions",
    ),
    "contents": GitHubUserTokenReadProbe(
        "contents",
        "/repos/{owner}/{repo}/contents",
    ),
    "environments": GitHubUserTokenReadProbe(
        "environments",
        "/repos/{owner}/{repo}/environments/{environment_name}/secrets",
        {"per_page": "1"},
        needs_existing_environment=True,
        unavailable_reason=(
            "GitHub only exposes non-mutating Environments checks inside an "
            "existing environment."
        ),
    ),
    "issues": GitHubUserTokenReadProbe(
        "issues",
        "/repos/{owner}/{repo}/issues",
        {"per_page": "1", "state": "all"},
    ),
    "metadata": GitHubUserTokenReadProbe(
        "metadata",
        "/repos/{owner}/{repo}",
    ),
    "pull_requests": GitHubUserTokenReadProbe(
        "pull_requests",
        "/repos/{owner}/{repo}/pulls",
        {"per_page": "1", "state": "all"},
    ),
    "secrets": GitHubUserTokenReadProbe(
        "secrets",
        "/repos/{owner}/{repo}/actions/secrets",
        {"per_page": "1"},
    ),
    "variables": GitHubUserTokenReadProbe(
        "variables",
        "/repos/{owner}/{repo}/actions/variables",
        {"per_page": "1"},
    ),
    "workflows": GitHubUserTokenReadProbe(
        "workflows",
        None,
        unavailable_reason=(
            "GitHub does not expose a read-only Workflows permission endpoint."
        ),
    ),
}

_ACCESS_LEVELS = {ACCESS_READ: 1, ACCESS_WRITE: 2}


def repository_permission_lines() -> tuple[str, ...]:
    """Human-readable repository permission requirements."""
    return tuple(
        f"{permission.label}: {permission.access}"
        for permission in REQUIRED_REPOSITORY_USER_TOKEN_PERMISSIONS
    )


def repository_permission_sentence() -> str:
    """Comma-separated human sentence for the required permission contract."""
    return ", ".join(repository_permission_lines())


def scoped_token_scope_lines() -> tuple[str, ...]:
    """Human-readable scope requirements for scope-bearing tokens."""
    return tuple(REQUIRED_SCOPED_USER_TOKEN_SCOPES)


def repository_read_probe(permission_key: str) -> GitHubUserTokenReadProbe:
    """Return the non-mutating probe declaration for a required permission."""
    return NON_MUTATING_REPOSITORY_USER_TOKEN_READ_PROBES[permission_key]


def repository_read_probe_keys() -> tuple[str, ...]:
    """Permission keys that have an explicit non-mutating probe declaration."""
    return tuple(NON_MUTATING_REPOSITORY_USER_TOKEN_READ_PROBES)


def evaluate_scoped_token_scopes(scopes: Iterable[str]) -> dict[str, object]:
    """Return whether GitHub's X-OAuth-Scopes satisfy Yoke's contract."""
    granted = {str(scope).strip() for scope in scopes if str(scope).strip()}
    missing = [
        scope for scope in REQUIRED_SCOPED_USER_TOKEN_SCOPES
        if scope not in granted
    ]
    return {
        "ok": not missing,
        "mode": "scoped_token",
        "required": list(REQUIRED_SCOPED_USER_TOKEN_SCOPES),
        "granted": sorted(granted),
        "missing": missing,
    }


def scoped_token_can_create_repos(scopes: Iterable[str]) -> dict[str, object]:
    """Tri-state create-repo capability derived from X-OAuth-Scopes."""
    granted = {str(scope).strip() for scope in scopes if str(scope).strip()}
    if CREATE_REPO_SCOPE_PRIVATE in granted:
        return {
            "can_create": True,
            "create_private": True,
            "basis": "scope:repo",
        }
    if CREATE_REPO_SCOPE_PUBLIC in granted:
        return {
            "can_create": True,
            "create_private": False,
            "basis": "scope:public_repo",
        }
    return {
        "can_create": False,
        "create_private": False,
        "basis": "scope:none",
    }


def permission_level_satisfies(granted: str, required: str) -> bool:
    """True when a repository permission level grants the required access."""
    return _ACCESS_LEVELS.get(granted, 0) >= _ACCESS_LEVELS.get(required, 0)


def evaluate_repository_permissions(
    permissions: Mapping[str, str],
) -> dict[str, object]:
    """Evaluate an explicit repository permission map when one is available."""
    normalized = {
        str(key).strip(): str(value).strip()
        for key, value in permissions.items()
        if str(key).strip() and str(value).strip()
    }
    missing = []
    for required in REQUIRED_REPOSITORY_USER_TOKEN_PERMISSIONS:
        granted = normalized.get(required.key)
        if not granted or not permission_level_satisfies(granted, required.access):
            missing.append({
                "key": required.key,
                "label": required.label,
                "required": required.access,
                "granted": granted,
            })
    return {
        "ok": not missing,
        "mode": "repository_token",
        "required": [
            {
                "key": permission.key,
                "label": permission.label,
                "access": permission.access,
            }
            for permission in REQUIRED_REPOSITORY_USER_TOKEN_PERMISSIONS
        ],
        "granted": normalized,
        "missing": missing,
    }


__all__ = [
    "ACCESS_READ",
    "ACCESS_WRITE",
    "CREATE_REPO_SCOPE_PRIVATE",
    "CREATE_REPO_SCOPE_PUBLIC",
    "GitHubUserTokenPermission",
    "GitHubUserTokenReadProbe",
    "NON_MUTATING_REPOSITORY_USER_TOKEN_READ_PROBES",
    "REQUIRED_SCOPED_USER_TOKEN_SCOPES",
    "REQUIRED_REPOSITORY_USER_TOKEN_PERMISSIONS",
    "scoped_token_can_create_repos",
    "scoped_token_scope_lines",
    "evaluate_scoped_token_scopes",
    "evaluate_repository_permissions",
    "repository_permission_lines",
    "repository_permission_sentence",
    "repository_read_probe",
    "repository_read_probe_keys",
    "permission_level_satisfies",
]
