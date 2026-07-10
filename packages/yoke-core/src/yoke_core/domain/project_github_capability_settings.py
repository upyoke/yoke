"""Canonical nonsecret GitHub capability settings for a repo binding."""

from __future__ import annotations

from typing import Any, Mapping

from yoke_contracts.github_origin import validate_github_api_endpoint

from yoke_core.domain import db_backend, json_helper
from yoke_core.domain.db_helpers import query_one
from yoke_core.domain.project_github_auth_models import GITHUB_CAPABILITY_TYPE


GITHUB_OPTIONAL_SETTINGS = frozenset({"ci_oidc_manage_provider"})


def normalize_github_capability_type(cap_type: str) -> str:
    """Canonicalize case variants without changing other capability names."""
    value = str(cap_type)
    if value.strip().casefold() == GITHUB_CAPABILITY_TYPE:
        return GITHUB_CAPABILITY_TYPE
    return value


def reject_github_capability_secret_write(cap_type: str) -> None:
    """Keep retired GitHub secret rows readable but permanently write-closed."""
    if normalize_github_capability_type(cap_type) == GITHUB_CAPABILITY_TYPE:
        raise ValueError(
            "GitHub capability secrets are retired stranded data; new writes "
            "are refused. Connect or rebind the repository through the GitHub "
            "App binding surface."
        )


def reject_github_capability_full_settings_write(cap_type: str) -> str:
    """Refuse generic replacement of binding-projected GitHub settings."""
    normalized = normalize_github_capability_type(cap_type)
    if normalized == GITHUB_CAPABILITY_TYPE:
        raise ValueError(
            "GitHub capability settings are binding-owned; generic full-document "
            "create/set is refused. Use the GitHub App binding surface; only "
            "ci_oidc_manage_provider may be changed with merge-settings."
        )
    return normalized


def validate_github_capability_merge_assignments(
    cap_type: str,
    assignments: dict[str, Any],
) -> str:
    """Allow only the optional boolean setting through generic merge."""
    normalized = normalize_github_capability_type(cap_type)
    if normalized != GITHUB_CAPABILITY_TYPE:
        return normalized
    invalid = sorted(set(assignments) - GITHUB_OPTIONAL_SETTINGS)
    if invalid:
        raise ValueError(
            "GitHub capability settings are binding-owned; merge-settings may "
            "change only ci_oidc_manage_provider"
        )
    if any(not isinstance(value, bool) for value in assignments.values()):
        raise ValueError("GitHub ci_oidc_manage_provider must be a boolean")
    return normalized


def assert_github_capability_merge_target(
    conn: Any,
    project_id: int,
    cap_type: str,
) -> None:
    """Require an existing canonical capability projected from a live binding."""
    if normalize_github_capability_type(cap_type) != GITHUB_CAPABILITY_TYPE:
        return
    placeholder = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = query_one(
        conn,
        "SELECT b.github_repo, b.installation_id, b.repository_id, b.api_url, "
        "b.permissions, c.settings "
        "FROM project_github_repo_bindings b JOIN project_capabilities c "
        "ON c.project_id=b.project_id AND c.type='github' "
        f"WHERE b.project_id={placeholder}",
        (project_id,),
    )
    if row is None:
        raise ValueError(
            "GitHub merge-settings requires an existing GitHub App repo binding"
        )
    try:
        current = json_helper.loads_text(str(row["settings"] or "{}"))
    except Exception as exc:
        raise ValueError(
            "stored GitHub capability settings are not canonical; rebind the repo"
        ) from exc
    expected = build_github_capability_settings(
        conn,
        project_id,
        github_repo=str(row["github_repo"]),
        installation_id=str(row["installation_id"]),
        repository_id=str(row["repository_id"]),
        api_url=str(row["api_url"]),
        permissions=_permissions_mapping(row["permissions"]),
    )
    if current != expected:
        raise ValueError(
            "stored GitHub capability settings do not match the verified binding; "
            "rebind the repo before changing optional settings"
        )


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
    placeholder = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = query_one(
        conn,
        f"SELECT COALESCE(settings, '{{}}') AS settings "
        f"FROM project_capabilities WHERE project_id={placeholder} "
        f"AND type={placeholder}",
        (project_id, "github"),
    )
    existing: dict[str, Any] = {}
    if row is not None:
        try:
            loaded = json_helper.loads_text(str(row["settings"] or "{}"))
        except Exception:
            loaded = {}
        if isinstance(loaded, dict):
            existing = {str(key): value for key, value in loaded.items()}
    owner, separator, name = str(github_repo).partition("/")
    if not separator or not owner or not name or "/" in name:
        raise ValueError("verified GitHub repository must be owner/name")
    settings = {
        key: existing[key]
        for key in GITHUB_OPTIONAL_SETTINGS
        if isinstance(existing.get(key), bool)
    }
    settings.update({
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
    })
    return settings


def _permissions_mapping(value: Any) -> Mapping[str, Any]:
    try:
        loaded = json_helper.loads_text(str(value or "{}"))
    except Exception as exc:
        raise ValueError(
            "stored GitHub binding permissions are not canonical; rebind the repo"
        ) from exc
    if not isinstance(loaded, dict):
        raise ValueError(
            "stored GitHub binding permissions are not canonical; rebind the repo"
        )
    return loaded


__all__ = [
    "GITHUB_OPTIONAL_SETTINGS",
    "assert_github_capability_merge_target",
    "build_github_capability_settings",
    "normalize_github_capability_type",
    "reject_github_capability_full_settings_write",
    "reject_github_capability_secret_write",
    "validate_github_capability_merge_assignments",
]
