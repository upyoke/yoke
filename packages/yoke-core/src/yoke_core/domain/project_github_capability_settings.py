"""Canonical nonsecret GitHub capability settings for a repo binding."""

from __future__ import annotations

from typing import Any, Mapping

from yoke_contracts.github_origin import validate_github_api_endpoint

from yoke_core.domain.project_github_auth_models import GITHUB_CAPABILITY_TYPE


def normalize_github_capability_type(cap_type: str) -> str:
    """Canonicalize case variants without changing other capability names."""
    value = str(cap_type)
    if value.strip().casefold() == GITHUB_CAPABILITY_TYPE:
        return GITHUB_CAPABILITY_TYPE
    return value


def reject_github_capability_secret_write(cap_type: str) -> None:
    """Refuse generic writes to the retired GitHub secret surface."""
    if normalize_github_capability_type(cap_type) == GITHUB_CAPABILITY_TYPE:
        raise ValueError(
            "GitHub capability secrets are retired; new writes are refused. "
            "Connect or rebind the repository through the GitHub App binding "
            "surface."
        )


def reject_github_capability_secret_read(cap_type: str) -> None:
    """Refuse reads that could disclose retired project GitHub credentials."""
    if normalize_github_capability_type(cap_type) == GITHUB_CAPABILITY_TYPE:
        raise ValueError(
            "GitHub capability secrets are retired and cannot be read. Use the "
            "GitHub App connection and project binding surfaces."
        )


def reject_github_capability_full_settings_write(cap_type: str) -> str:
    """Refuse generic replacement of binding-projected GitHub settings."""
    normalized = normalize_github_capability_type(cap_type)
    if normalized == GITHUB_CAPABILITY_TYPE:
        raise ValueError(
            "GitHub capability settings are binding-owned; generic full-document "
            "create/set is refused. Use the GitHub App binding surface."
        )
    return normalized


def validate_github_capability_merge_assignments(
    cap_type: str,
    assignments: dict[str, Any],
) -> str:
    """Refuse generic merges into binding-projected GitHub settings."""
    del assignments
    normalized = normalize_github_capability_type(cap_type)
    if normalized == GITHUB_CAPABILITY_TYPE:
        raise ValueError(
            "GitHub capability settings are binding-owned; merge-settings is "
            "refused. Use the GitHub App binding surface."
        )
    return normalized


def build_github_capability_settings(
    conn: Any,
    project_id: int,
    *,
    github_repo: str,
    installation_id: str,
    repository_id: str,
    api_url: str,
    permissions: Mapping[str, Any],
) -> dict[str, Any]:
    """Project a verified binding into the current capability-settings shape."""
    del conn, project_id
    owner, separator, name = str(github_repo).partition("/")
    if not separator or not owner or not name or "/" in name:
        raise ValueError("verified GitHub repository must be owner/name")
    settings = {
        "repo_owner": owner,
        "repo_name": name,
        "installation_id": str(installation_id),
        "repository_id": str(repository_id),
        "api_url": validate_github_api_endpoint(api_url).base_url,
        "permissions": {
            str(key): str(value)
            for key, value in permissions.items()
            if str(key).strip() and str(value).strip()
        },
    }
    return settings


__all__ = [
    "build_github_capability_settings",
    "normalize_github_capability_type",
    "reject_github_capability_full_settings_write",
    "reject_github_capability_secret_read",
    "reject_github_capability_secret_write",
    "validate_github_capability_merge_assignments",
]
