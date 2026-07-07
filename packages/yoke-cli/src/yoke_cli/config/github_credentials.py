"""Read-only machine GitHub credential helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from yoke_contracts.machine_config import schema as contract


class GitHubCredentialError(RuntimeError):
    """The configured GitHub credential cannot be read."""


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
                f"GitHub token file is missing: {path}",
                "Run `yoke github connect TOKEN` to import a fresh token.",
            ))
    elif kind:
        issues.append(_issue(
            "error",
            "github_credential_kind_unknown",
            f"unsupported GitHub credential kind: {kind}",
            "Use token_file credential storage.",
        ))
    else:
        issues.append(_issue(
            "error",
            "github_credential_source_missing",
            "machine GitHub credential_source is missing a kind",
            "Run `yoke github connect TOKEN`.",
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
        raise GitHubCredentialError(f"GitHub token file is missing: {token_path}")
    try:
        token = token_path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise GitHubCredentialError(
            f"GitHub token file is unreadable: {token_path}"
        ) from exc
    if not token:
        raise GitHubCredentialError(f"GitHub token file is empty: {token_path}")
    return token


def _issue(severity: str, code: str, message: str, hint: str = "") -> dict[str, str]:
    issue = {"severity": severity, "code": code, "message": message}
    if hint:
        issue["hint"] = hint
    return issue


__all__ = [
    "GitHubCredentialError",
    "credential_status",
    "read_token_file",
    "read_token_source",
]
