"""Payload helpers for GitHub App repository binding status."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from yoke_contracts.github_origin import (
    GitHubApiOriginError,
    normalize_github_repository,
)
from yoke_contracts.github_app_installation_permissions import (
    ACCESS_READ,
    ACCESS_WRITE,
    REQUIRED_GITHUB_APP_REPOSITORY_PERMISSION_LEVELS,
)

from yoke_core.domain import json_helper

_PERMISSION_LEVELS = {"none": 0, ACCESS_READ: 1, ACCESS_WRITE: 2}


def normalize_github_repo(value: Any) -> str:
    """Return canonical ``owner/repo`` from a GitHub repo or clone URL."""
    try:
        return normalize_github_repository(str(value or "")).casefold()
    except GitHubApiOriginError:
        return ""


def automation_status(
    binding: Optional[dict[str, Any]],
    installation: Optional[dict[str, Any]],
    permission_status: Mapping[str, Any],
) -> dict[str, Any]:
    if binding is None:
        return {"available": False, "reason": "repo_not_bound"}
    if installation is None:
        return {"available": False, "reason": "installation_missing"}
    if str(binding.get("api_url") or "") != str(installation.get("api_url") or ""):
        return {"available": False, "reason": "api_origin_mismatch"}
    if installation.get("status") != "active":
        return {
            "available": False,
            "reason": f"installation_{installation.get('status') or 'unavailable'}",
        }
    if permission_status.get("status") != "satisfied":
        if permission_status.get("status") == "unknown":
            return {"available": False, "reason": "permissions_unverified"}
        return {"available": False, "reason": "missing_permissions"}
    if binding.get("status") != "active":
        return {
            "available": False,
            "reason": f"binding_{binding.get('status') or 'unavailable'}",
        }
    return {"available": True, "reason": "bound"}


def permission_status(
    permissions: Mapping[str, Any],
    required_permissions: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    if not permissions:
        return {
            "status": "unknown",
            "missing": [],
            "hint": ("Reconnect the GitHub App so Yoke can verify its required repository permissions."),
        }
    missing: list[str] = []
    required = required_permissions or REQUIRED_GITHUB_APP_REPOSITORY_PERMISSION_LEVELS
    for permission, required_level in required.items():
        actual = _permission_level(permissions.get(permission))
        normalized_required = str(required_level or "").strip().lower()
        if normalized_required not in {ACCESS_READ, ACCESS_WRITE}:
            raise ValueError("required GitHub permission levels must be exactly read or write")
        required_value = _PERMISSION_LEVELS[normalized_required]
        if actual < required_value:
            missing.append(permission)
    if not missing:
        return {"status": "satisfied", "missing": []}
    return {
        "status": "missing",
        "missing": missing,
        "hint": (f"Grant the GitHub App the required permissions, then retry the binding: {', '.join(missing)}."),
    }


def binding_payload(row: Any) -> Optional[dict[str, Any]]:
    if row is None:
        return None
    return {
        "project_id": int(row["project_id"]),
        "installation_id": str(row["installation_id"]),
        "repository_id": str(row["repository_id"] or ""),
        "api_url": str(row["api_url"] or ""),
        "github_repo": str(row["github_repo"] or ""),
        "default_branch": str(row["default_branch"] or ""),
        "status": str(row["status"] or ""),
        "permissions": permissions_dict(row["permissions"]),
        "last_verified_at": str(row["last_verified_at"] or ""),
        "last_error": str(row["last_error"] or ""),
        "last_sync_at": str(row["last_sync_at"] or ""),
        "last_sync_outcome": str(row["last_sync_outcome"] or ""),
        "last_sync_error": str(row["last_sync_error"] or ""),
    }


def installation_payload(row: Any) -> Optional[dict[str, Any]]:
    if row is None:
        return None
    return {
        "installation_id": str(row["installation_id"]),
        "api_url": str(row["api_url"] or ""),
        "account_id": str(row["account_id"] or ""),
        "account_login": str(row["account_login"] or ""),
        "account_type": str(row["account_type"] or ""),
        "repository_selection": str(row["repository_selection"] or ""),
        "permissions": permissions_dict(row["permissions"]),
        "status": str(row["status"] or ""),
        "last_verified_at": str(row["last_verified_at"] or ""),
        "last_error": str(row["last_error"] or ""),
    }


def permissions_text(value: Optional[Mapping[str, Any]]) -> str:
    if value is None:
        return "{}"
    return json_helper.dumps_compact({str(key): str(raw_value) for key, raw_value in value.items() if str(key).strip()})


def permissions_dict(value: Any) -> dict[str, Any]:
    raw = str(value or "{}")
    try:
        loaded = json_helper.loads_text(raw)
    except Exception:
        return {}
    if not isinstance(loaded, dict):
        return {}
    return {str(key): raw_value for key, raw_value in loaded.items()}


def _permission_level(value: Any) -> int:
    return _PERMISSION_LEVELS.get(str(value or "none").strip().lower(), 0)


__all__ = [
    "REQUIRED_GITHUB_APP_REPOSITORY_PERMISSION_LEVELS",
    "automation_status",
    "binding_payload",
    "installation_payload",
    "normalize_github_repo",
    "permission_status",
    "permissions_text",
]
