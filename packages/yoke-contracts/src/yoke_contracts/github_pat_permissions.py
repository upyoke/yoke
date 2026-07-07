"""Shared GitHub PAT permission contract for Yoke machine onboarding."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

ACCESS_READ = "read"
ACCESS_WRITE = "write"


@dataclass(frozen=True)
class GitHubPatPermission:
    """One fine-grained PAT permission Yoke needs on repository resources."""

    key: str
    label: str
    access: str


@dataclass(frozen=True)
class GitHubPatReadProbe:
    """A non-mutating API check for one fine-grained PAT permission."""

    key: str
    path_template: str | None
    query: Mapping[str, str] | None = None
    needs_existing_environment: bool = False
    unavailable_reason: str = ""


REQUIRED_FINE_GRAINED_PAT_PERMISSIONS = (
    GitHubPatPermission("actions", "Actions", ACCESS_WRITE),
    GitHubPatPermission("administration", "Administration", ACCESS_WRITE),
    GitHubPatPermission("contents", "Contents", ACCESS_WRITE),
    GitHubPatPermission("environments", "Environments", ACCESS_WRITE),
    GitHubPatPermission("issues", "Issues", ACCESS_WRITE),
    GitHubPatPermission("metadata", "Metadata", ACCESS_READ),
    GitHubPatPermission("pull_requests", "Pull requests", ACCESS_WRITE),
    GitHubPatPermission("secrets", "Secrets", ACCESS_WRITE),
    GitHubPatPermission("variables", "Variables", ACCESS_WRITE),
    GitHubPatPermission("workflows", "Workflows", ACCESS_WRITE),
)

# Classic PATs do not expose per-repository permission names. GitHub reports
# classic grants through X-OAuth-Scopes; repo covers private repository read/write
# APIs and workflow is required for workflow file/API access.
REQUIRED_CLASSIC_PAT_SCOPES = ("repo", "workflow")

# Classic scopes that grant repository creation. `repo` covers private + public
# create; `public_repo` covers public-only create. Fine-grained PATs expose no
# create grant via API, so they are classified UNKNOWN, never True/False.
CREATE_REPO_SCOPE_PRIVATE = "repo"
CREATE_REPO_SCOPE_PUBLIC = "public_repo"

NON_MUTATING_FINE_GRAINED_PAT_READ_PROBES = {
    "actions": GitHubPatReadProbe(
        "actions",
        "/repos/{owner}/{repo}/actions/runs",
        {"per_page": "1"},
    ),
    "administration": GitHubPatReadProbe(
        "administration",
        "/repos/{owner}/{repo}/actions/permissions",
    ),
    "contents": GitHubPatReadProbe(
        "contents",
        "/repos/{owner}/{repo}/contents",
    ),
    "environments": GitHubPatReadProbe(
        "environments",
        "/repos/{owner}/{repo}/environments/{environment_name}/secrets",
        {"per_page": "1"},
        needs_existing_environment=True,
        unavailable_reason=(
            "GitHub only exposes non-mutating Environments checks inside an "
            "existing environment."
        ),
    ),
    "issues": GitHubPatReadProbe(
        "issues",
        "/repos/{owner}/{repo}/issues",
        {"per_page": "1", "state": "all"},
    ),
    "metadata": GitHubPatReadProbe(
        "metadata",
        "/repos/{owner}/{repo}",
    ),
    "pull_requests": GitHubPatReadProbe(
        "pull_requests",
        "/repos/{owner}/{repo}/pulls",
        {"per_page": "1", "state": "all"},
    ),
    "secrets": GitHubPatReadProbe(
        "secrets",
        "/repos/{owner}/{repo}/actions/secrets",
        {"per_page": "1"},
    ),
    "variables": GitHubPatReadProbe(
        "variables",
        "/repos/{owner}/{repo}/actions/variables",
        {"per_page": "1"},
    ),
    "workflows": GitHubPatReadProbe(
        "workflows",
        None,
        unavailable_reason=(
            "GitHub does not expose a read-only Workflows permission endpoint."
        ),
    ),
}

_ACCESS_LEVELS = {ACCESS_READ: 1, ACCESS_WRITE: 2}


def fine_grained_permission_lines() -> tuple[str, ...]:
    """Human instructions for the fine-grained PAT settings page."""
    return tuple(
        f"{permission.label}: {permission.access}"
        for permission in REQUIRED_FINE_GRAINED_PAT_PERMISSIONS
    )


def fine_grained_permission_sentence() -> str:
    """Comma-separated human sentence for the required permission contract."""
    return ", ".join(fine_grained_permission_lines())


def classic_scope_lines() -> tuple[str, ...]:
    """Human instructions for classic PAT scopes."""
    return tuple(REQUIRED_CLASSIC_PAT_SCOPES)


def fine_grained_read_probe(permission_key: str) -> GitHubPatReadProbe:
    """Return the non-mutating probe declaration for a required permission."""
    return NON_MUTATING_FINE_GRAINED_PAT_READ_PROBES[permission_key]


def fine_grained_read_probe_keys() -> tuple[str, ...]:
    """Permission keys that have an explicit non-mutating probe declaration."""
    return tuple(NON_MUTATING_FINE_GRAINED_PAT_READ_PROBES)


def evaluate_classic_scopes(scopes: Iterable[str]) -> dict[str, object]:
    """Return whether GitHub's X-OAuth-Scopes satisfy Yoke's contract."""
    granted = {str(scope).strip() for scope in scopes if str(scope).strip()}
    missing = [
        scope for scope in REQUIRED_CLASSIC_PAT_SCOPES
        if scope not in granted
    ]
    return {
        "ok": not missing,
        "mode": "classic",
        "required": list(REQUIRED_CLASSIC_PAT_SCOPES),
        "granted": sorted(granted),
        "missing": missing,
    }


def classic_can_create_repos(scopes: Iterable[str]) -> dict[str, object]:
    """Tri-state create-repo capability derived from classic X-OAuth-Scopes."""
    granted = {str(scope).strip() for scope in scopes if str(scope).strip()}
    if CREATE_REPO_SCOPE_PRIVATE in granted:
        return {
            "can_create": True,
            "create_private": True,
            "basis": "classic_scope:repo",
        }
    if CREATE_REPO_SCOPE_PUBLIC in granted:
        return {
            "can_create": True,
            "create_private": False,
            "basis": "classic_scope:public_repo",
        }
    return {
        "can_create": False,
        "create_private": False,
        "basis": "classic_scope:none",
    }


def permission_level_satisfies(granted: str, required: str) -> bool:
    """True when a fine-grained level grants at least the required access."""
    return _ACCESS_LEVELS.get(granted, 0) >= _ACCESS_LEVELS.get(required, 0)


def evaluate_fine_grained_permissions(
    permissions: Mapping[str, str],
) -> dict[str, object]:
    """Evaluate an explicit fine-grained permission map when one is available."""
    normalized = {
        str(key).strip(): str(value).strip()
        for key, value in permissions.items()
        if str(key).strip() and str(value).strip()
    }
    missing = []
    for required in REQUIRED_FINE_GRAINED_PAT_PERMISSIONS:
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
        "mode": "fine_grained",
        "required": [
            {
                "key": permission.key,
                "label": permission.label,
                "access": permission.access,
            }
            for permission in REQUIRED_FINE_GRAINED_PAT_PERMISSIONS
        ],
        "granted": normalized,
        "missing": missing,
    }


__all__ = [
    "ACCESS_READ",
    "ACCESS_WRITE",
    "CREATE_REPO_SCOPE_PRIVATE",
    "CREATE_REPO_SCOPE_PUBLIC",
    "GitHubPatPermission",
    "GitHubPatReadProbe",
    "NON_MUTATING_FINE_GRAINED_PAT_READ_PROBES",
    "REQUIRED_CLASSIC_PAT_SCOPES",
    "REQUIRED_FINE_GRAINED_PAT_PERMISSIONS",
    "classic_can_create_repos",
    "classic_scope_lines",
    "evaluate_classic_scopes",
    "evaluate_fine_grained_permissions",
    "fine_grained_permission_lines",
    "fine_grained_permission_sentence",
    "fine_grained_read_probe",
    "fine_grained_read_probe_keys",
    "permission_level_satisfies",
]
