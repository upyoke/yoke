"""Payload helpers for GitHub App repository binding status."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from yoke_core.domain import json_helper


REQUIRED_AUTOMATION_PERMISSIONS: Mapping[str, str] = {
    "metadata": "read",
    "issues": "write",
    "pull_requests": "write",
    "contents": "write",
    "actions": "write",
    "workflows": "write",
    "secrets": "write",
    "variables": "write",
}

_PERMISSION_LEVELS = {"none": 0, "read": 1, "write": 2, "admin": 3}


def normalize_github_repo(value: Any) -> str:
    """Return canonical ``owner/repo`` from a GitHub repo or clone URL."""
    cleaned = str(value or "").strip()
    if not cleaned:
        return ""
    cleaned = cleaned.removesuffix(".git")
    if cleaned.startswith("git@github.com:"):
        cleaned = cleaned.split(":", 1)[1]
    else:
        marker = "github.com/"
        if marker in cleaned:
            cleaned = cleaned.split(marker, 1)[1]
    cleaned = cleaned.strip("/")
    parts = [part for part in cleaned.split("/") if part]
    if len(parts) < 2:
        return ""
    return f"{parts[0]}/{parts[1]}".lower()


def automation_status(
    binding: Optional[dict[str, Any]],
    installation: Optional[dict[str, Any]],
    permission_status: Mapping[str, Any],
) -> dict[str, Any]:
    if binding is None:
        return {"available": False, "reason": "repo_not_bound"}
    if installation is None:
        return {"available": False, "reason": "installation_missing"}
    if installation.get("status") != "active":
        return {
            "available": False,
            "reason": f"installation_{installation.get('status') or 'unavailable'}",
        }
    if binding.get("status") != "active":
        return {
            "available": False,
            "reason": f"binding_{binding.get('status') or 'unavailable'}",
        }
    if permission_status.get("status") == "missing":
        return {"available": False, "reason": "missing_permissions"}
    return {"available": True, "reason": "bound"}


def permission_status(permissions: Mapping[str, Any]) -> dict[str, Any]:
    if not permissions:
        return {"status": "unknown", "missing": []}
    missing: list[str] = []
    for permission, required_level in REQUIRED_AUTOMATION_PERMISSIONS.items():
        actual = _permission_level(permissions.get(permission))
        required = _permission_level(required_level)
        if actual < required:
            missing.append(permission)
    return {
        "status": "satisfied" if not missing else "missing",
        "missing": missing,
    }


def binding_payload(row: Any) -> Optional[dict[str, Any]]:
    if row is None:
        return None
    return {
        "project_id": int(row["project_id"]),
        "installation_id": str(row["installation_id"]),
        "repository_id": str(row["repository_id"] or ""),
        "github_repo": str(row["github_repo"] or ""),
        "default_branch": str(row["default_branch"] or ""),
        "status": str(row["status"] or ""),
        "permissions": permissions_dict(row["permissions"]),
        "last_verified_at": str(row["last_verified_at"] or ""),
        "last_error": str(row["last_error"] or ""),
    }


def installation_payload(row: Any) -> Optional[dict[str, Any]]:
    if row is None:
        return None
    return {
        "installation_id": str(row["installation_id"]),
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
    return json_helper.dumps_compact({
        str(key): str(raw_value)
        for key, raw_value in value.items()
        if str(key).strip()
    })


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
    "REQUIRED_AUTOMATION_PERMISSIONS",
    "automation_status",
    "binding_payload",
    "installation_payload",
    "normalize_github_repo",
    "permission_status",
    "permissions_text",
]
