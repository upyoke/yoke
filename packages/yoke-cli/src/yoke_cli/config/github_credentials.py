"""Read-only machine GitHub connection helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from yoke_contracts.machine_config import schema as contract


class GitHubCredentialError(RuntimeError):
    """The configured GitHub credential cannot be read."""


def authorization_status(authorization: Mapping[str, Any]) -> dict[str, Any]:
    """Return local status for a GitHub App user authorization block."""
    kind = str(authorization.get("kind") or "")
    status_value = str(authorization.get("status") or "")
    raw_ref = str(authorization.get("refresh_credential_ref") or "").strip()
    status: dict[str, Any] = {
        "kind": kind or None,
        "status": status_value or None,
        "login": str(authorization.get("login") or ""),
        "github_user_id": authorization.get("github_user_id"),
        "refresh_credential_ref": raw_ref,
        "present": False,
    }
    issues: list[dict[str, str]] = []
    if kind != contract.GITHUB_AUTH_KIND_USER_AUTHORIZATION:
        issues.append(_issue(
            "error",
            "github_authorization_kind_unknown",
            f"unsupported GitHub authorization kind: {kind or '<missing>'}",
            "Reconnect GitHub through the Yoke GitHub App.",
        ))
    if raw_ref:
        refresh_path = Path(raw_ref).expanduser()
        status.update({
            "refresh_credential_ref": str(refresh_path),
            "present": refresh_path.is_file(),
        })
        if not refresh_path.is_file():
            issues.append(_issue(
                "error",
                "github_refresh_credential_missing",
                f"GitHub App refresh credential is missing: {refresh_path}",
                "Reconnect GitHub through the Yoke GitHub App.",
            ))
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


def credential_status(source: Mapping[str, Any]) -> dict[str, Any]:
    kind = str(source.get("kind") or "")
    status: dict[str, Any] = {"kind": kind or None, "present": False}
    issues = []
    if kind == contract.CREDENTIAL_KIND_TOKEN_FILE:
        path = Path(str(source.get("path") or "")).expanduser()
        status.update({"path": str(path), "present": path.is_file()})
        if not path.is_file():
            issues.append(_issue(
                "error",
                "github_token_missing",
                f"GitHub credential file is missing: {path}",
                "Run `yoke github connect TOKEN` to import a fresh token.",
            ))
    elif kind:
        issues.append(_issue(
            "error",
            "github_credential_kind_unknown",
            f"unsupported GitHub credential kind: {kind}",
            "Reconnect GitHub through the Yoke GitHub App.",
        ))
    else:
        issues.append(_issue(
            "error",
            "github_credential_source_missing",
            "machine GitHub credential_source is missing a kind",
            "Reconnect GitHub through the Yoke GitHub App.",
        ))
    status["issues"] = issues
    return status


def read_token_source(source: Mapping[str, Any]) -> str:
    kind = str(source.get("kind") or "")
    if kind == contract.CREDENTIAL_KIND_TOKEN_FILE:
        return read_token_file(Path(str(source.get("path") or "")).expanduser())
    raise GitHubCredentialError(
        "GitHub credential_source.kind must be 'token_file'"
    )


def read_token_file(token_path: Path) -> str:
    if not token_path.is_file():
        raise GitHubCredentialError(f"GitHub credential file is missing: {token_path}")
    try:
        token = token_path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise GitHubCredentialError(
            f"GitHub credential file is unreadable: {token_path}"
        ) from exc
    if not token:
        raise GitHubCredentialError(f"GitHub credential file is empty: {token_path}")
    return token


def _issue(severity: str, code: str, message: str, hint: str = "") -> dict[str, str]:
    issue = {"severity": severity, "code": code, "message": message}
    if hint:
        issue["hint"] = hint
    return issue


__all__ = [
    "GitHubCredentialError",
    "authorization_status",
    "credential_status",
    "read_token_file",
    "read_token_source",
]
