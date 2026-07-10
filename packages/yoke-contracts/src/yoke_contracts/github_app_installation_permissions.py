"""Required repository permissions for Yoke's GitHub App installations."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

ACCESS_READ = "read"
ACCESS_WRITE = "write"
ADMINISTRATION_PERMISSION = "administration"

_ACTIONS_PERMISSION = "actions"
_CHECKS_PERMISSION = "checks"
_CONTENTS_PERMISSION = "contents"
_ISSUES_PERMISSION = "issues"
_METADATA_PERMISSION = "metadata"
_PULL_REQUESTS_PERMISSION = "pull_requests"
_SECRETS_PERMISSION = "secrets"
_VARIABLES_PERMISSION = "variables"
_WORKFLOWS_PERMISSION = "workflows"


def _permission_levels(permission: str, access: str) -> Mapping[str, str]:
    return MappingProxyType({permission: access})


GITHUB_ACTIONS_READ_PERMISSION_LEVELS = _permission_levels(
    _ACTIONS_PERMISSION, ACCESS_READ,
)
GITHUB_ACTIONS_WRITE_PERMISSION_LEVELS = _permission_levels(
    _ACTIONS_PERMISSION, ACCESS_WRITE,
)
GITHUB_ADMINISTRATION_READ_PERMISSION_LEVELS = _permission_levels(
    ADMINISTRATION_PERMISSION, ACCESS_READ,
)
GITHUB_ADMINISTRATION_WRITE_PERMISSION_LEVELS = _permission_levels(
    ADMINISTRATION_PERMISSION, ACCESS_WRITE,
)
GITHUB_CHECKS_READ_PERMISSION_LEVELS = _permission_levels(
    _CHECKS_PERMISSION, ACCESS_READ,
)
GITHUB_CHECKS_WRITE_PERMISSION_LEVELS = _permission_levels(
    _CHECKS_PERMISSION, ACCESS_WRITE,
)
GITHUB_CONTENTS_READ_PERMISSION_LEVELS = _permission_levels(
    _CONTENTS_PERMISSION, ACCESS_READ,
)
GITHUB_CONTENTS_WRITE_PERMISSION_LEVELS = _permission_levels(
    _CONTENTS_PERMISSION, ACCESS_WRITE,
)
GITHUB_ISSUES_READ_PERMISSION_LEVELS = _permission_levels(
    _ISSUES_PERMISSION, ACCESS_READ,
)
GITHUB_ISSUES_WRITE_PERMISSION_LEVELS = _permission_levels(
    _ISSUES_PERMISSION, ACCESS_WRITE,
)
GITHUB_METADATA_READ_PERMISSION_LEVELS = _permission_levels(
    _METADATA_PERMISSION, ACCESS_READ,
)
GITHUB_PULL_REQUESTS_READ_PERMISSION_LEVELS = _permission_levels(
    _PULL_REQUESTS_PERMISSION, ACCESS_READ,
)
GITHUB_PULL_REQUESTS_WRITE_PERMISSION_LEVELS = _permission_levels(
    _PULL_REQUESTS_PERMISSION, ACCESS_WRITE,
)
GITHUB_SECRETS_READ_PERMISSION_LEVELS = _permission_levels(
    _SECRETS_PERMISSION, ACCESS_READ,
)
GITHUB_SECRETS_WRITE_PERMISSION_LEVELS = _permission_levels(
    _SECRETS_PERMISSION, ACCESS_WRITE,
)
GITHUB_VARIABLES_READ_PERMISSION_LEVELS = _permission_levels(
    _VARIABLES_PERMISSION, ACCESS_READ,
)
GITHUB_VARIABLES_WRITE_PERMISSION_LEVELS = _permission_levels(
    _VARIABLES_PERMISSION, ACCESS_WRITE,
)
GITHUB_WORKFLOWS_READ_PERMISSION_LEVELS = _permission_levels(
    _WORKFLOWS_PERMISSION, ACCESS_READ,
)
GITHUB_WORKFLOWS_WRITE_PERMISSION_LEVELS = _permission_levels(
    _WORKFLOWS_PERMISSION, ACCESS_WRITE,
)

# Creating or updating repository environments uses Administration: write.
GITHUB_ENVIRONMENT_WRITE_PERMISSION_LEVELS = (
    GITHUB_ADMINISTRATION_WRITE_PERMISSION_LEVELS
)


@dataclass(frozen=True)
class GitHubAppRepositoryPermission:
    """One repository permission required from a GitHub App installation."""

    key: str
    label: str
    access: str


REQUIRED_GITHUB_APP_REPOSITORY_PERMISSIONS = (
    GitHubAppRepositoryPermission(_ACTIONS_PERMISSION, "Actions", ACCESS_WRITE),
    GitHubAppRepositoryPermission(_CHECKS_PERMISSION, "Checks", ACCESS_READ),
    GitHubAppRepositoryPermission(_CONTENTS_PERMISSION, "Contents", ACCESS_WRITE),
    GitHubAppRepositoryPermission(_ISSUES_PERMISSION, "Issues", ACCESS_WRITE),
    GitHubAppRepositoryPermission(_METADATA_PERMISSION, "Metadata", ACCESS_READ),
    GitHubAppRepositoryPermission(
        _PULL_REQUESTS_PERMISSION, "Pull requests", ACCESS_WRITE,
    ),
    GitHubAppRepositoryPermission(_SECRETS_PERMISSION, "Secrets", ACCESS_WRITE),
    GitHubAppRepositoryPermission(_VARIABLES_PERMISSION, "Variables", ACCESS_WRITE),
    GitHubAppRepositoryPermission(_WORKFLOWS_PERMISSION, "Workflows", ACCESS_WRITE),
)
REQUIRED_GITHUB_APP_REPOSITORY_PERMISSION_LEVELS: Mapping[str, str] = (
    MappingProxyType({
        item.key: item.access
        for item in REQUIRED_GITHUB_APP_REPOSITORY_PERMISSIONS
    })
)

_ACCESS_LEVELS = {ACCESS_READ: 1, ACCESS_WRITE: 2}


def required_repository_permission_lines() -> tuple[str, ...]:
    return tuple(
        f"{permission.label}: {permission.access}"
        for permission in REQUIRED_GITHUB_APP_REPOSITORY_PERMISSIONS
    )


def required_repository_permission_sentence() -> str:
    return ", ".join(required_repository_permission_lines())


def permission_level_satisfies(granted: str, required: str) -> bool:
    required_level = _ACCESS_LEVELS.get(required)
    return required_level is not None and _ACCESS_LEVELS.get(granted, 0) >= required_level


def evaluate_installation_repository_permissions(
    permissions: Mapping[str, str],
) -> dict[str, object]:
    """Evaluate one installation permission map against the App contract."""
    normalized = {
        str(key).strip(): str(value).strip()
        for key, value in permissions.items()
        if str(key).strip() and str(value).strip()
    }
    missing = []
    for required in REQUIRED_GITHUB_APP_REPOSITORY_PERMISSIONS:
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
        "mode": "github_app_installation",
        "required": [
            {"key": item.key, "label": item.label, "access": item.access}
            for item in REQUIRED_GITHUB_APP_REPOSITORY_PERMISSIONS
        ],
        "granted": normalized,
        "missing": missing,
    }


__all__ = [
    "ADMINISTRATION_PERMISSION",
    "ACCESS_READ",
    "ACCESS_WRITE",
    "GITHUB_ACTIONS_READ_PERMISSION_LEVELS",
    "GITHUB_ACTIONS_WRITE_PERMISSION_LEVELS",
    "GITHUB_ADMINISTRATION_READ_PERMISSION_LEVELS",
    "GITHUB_ADMINISTRATION_WRITE_PERMISSION_LEVELS",
    "GITHUB_CHECKS_READ_PERMISSION_LEVELS",
    "GITHUB_CHECKS_WRITE_PERMISSION_LEVELS",
    "GITHUB_CONTENTS_READ_PERMISSION_LEVELS",
    "GITHUB_CONTENTS_WRITE_PERMISSION_LEVELS",
    "GITHUB_ENVIRONMENT_WRITE_PERMISSION_LEVELS",
    "GITHUB_ISSUES_READ_PERMISSION_LEVELS",
    "GITHUB_ISSUES_WRITE_PERMISSION_LEVELS",
    "GITHUB_METADATA_READ_PERMISSION_LEVELS",
    "GITHUB_PULL_REQUESTS_READ_PERMISSION_LEVELS",
    "GITHUB_PULL_REQUESTS_WRITE_PERMISSION_LEVELS",
    "GITHUB_SECRETS_READ_PERMISSION_LEVELS",
    "GITHUB_SECRETS_WRITE_PERMISSION_LEVELS",
    "GITHUB_VARIABLES_READ_PERMISSION_LEVELS",
    "GITHUB_VARIABLES_WRITE_PERMISSION_LEVELS",
    "GITHUB_WORKFLOWS_READ_PERMISSION_LEVELS",
    "GITHUB_WORKFLOWS_WRITE_PERMISSION_LEVELS",
    "GitHubAppRepositoryPermission",
    "REQUIRED_GITHUB_APP_REPOSITORY_PERMISSIONS",
    "REQUIRED_GITHUB_APP_REPOSITORY_PERMISSION_LEVELS",
    "evaluate_installation_repository_permissions",
    "permission_level_satisfies",
    "required_repository_permission_lines",
    "required_repository_permission_sentence",
]
