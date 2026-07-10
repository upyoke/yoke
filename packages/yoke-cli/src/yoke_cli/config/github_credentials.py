"""Read-only machine GitHub connection helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from yoke_cli.config import github_git_credential_store as credential_store
from yoke_contracts.machine_config import schema as contract


def authorization_status(authorization: Mapping[str, Any]) -> dict[str, Any]:
    """Return local status for a GitHub App user authorization block."""
    kind = str(authorization.get("kind") or "")
    status_value = str(authorization.get("status") or "")
    raw_ref = str(authorization.get("refresh_credential_ref") or "").strip()
    status: dict[str, Any] = {
        "status": status_value or None,
        "login": str(authorization.get("login") or ""),
        "github_user_id": authorization.get("github_user_id"),
        "present": False,
    }
    issues: list[dict[str, str]] = []
    if kind != contract.GITHUB_AUTH_KIND_USER_AUTHORIZATION:
        issues.append(_issue(
            "error",
            "github_authorization_kind_unknown",
            "GitHub App authorization has an unsupported format",
            "Reconnect GitHub through the Yoke GitHub App.",
        ))
    if raw_ref:
        refresh_path = Path(raw_ref).expanduser()
        present = False
        try:
            credential_store.read_credential_document(refresh_path)
            present = True
        except credential_store.GitHubCredentialStoreError:
            issues.append(_issue(
                "error",
                "github_refresh_credential_invalid",
                "GitHub App refresh credential is missing, unsafe, or unreadable",
                "Reconnect GitHub through the Yoke GitHub App.",
            ))
        status.update({
            "present": present,
        })
    else:
        issues.append(_issue(
            "error",
            "github_refresh_credential_ref_missing",
            "GitHub App refresh credential reference is missing",
            "Reconnect GitHub through the Yoke GitHub App.",
        ))
    if status_value == "revoked":
        issues.append(_issue(
            "error",
            "github_authorization_revoked",
            "GitHub App user authorization has been revoked",
            "Reconnect GitHub through the Yoke GitHub App.",
        ))
    elif status_value == "pending":
        issues.append(_issue(
            "warning",
            "github_authorization_pending",
            "GitHub App user authorization is pending",
            "Complete the browser authorization flow.",
        ))
    elif status_value and status_value not in contract.GITHUB_AUTH_STATUSES:
        issues.append(_issue(
            "error",
            "github_authorization_status_unknown",
            f"unsupported GitHub authorization status: {status_value}",
            "Reconnect GitHub through the Yoke GitHub App.",
        ))
    status["issues"] = issues
    return status


def _issue(severity: str, code: str, message: str, hint: str = "") -> dict[str, str]:
    issue = {"severity": severity, "code": code, "message": message}
    if hint:
        issue["hint"] = hint
    return issue


__all__ = [
    "authorization_status",
]
