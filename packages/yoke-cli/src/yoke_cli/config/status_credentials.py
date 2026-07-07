"""Redacted credential status helpers for product ``yoke status``."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

from yoke_contracts.machine_config import schema as contract


def credential_status(
    source: Mapping[str, Any],
    *,
    config_path: Path,
) -> dict[str, Any]:
    kind = str(source.get("kind") or "")
    issues: list[dict[str, str]] = []
    status: dict[str, Any] = {"kind": kind or None, "present": False}
    if kind in (contract.CREDENTIAL_KIND_DSN_FILE, contract.CREDENTIAL_KIND_TOKEN_FILE):
        raw = str(source.get("path") or "")
        path = Path(raw).expanduser()
        if raw and not path.is_absolute():
            path = config_path.parent / path
        status.update({"path": str(path), "present": path.is_file()})
        if not path.is_file():
            label = "DSN" if kind == contract.CREDENTIAL_KIND_DSN_FILE else "token"
            issues.append(_issue(
                "error",
                "credential_missing",
                f"{label} file is missing: {path}",
                "Create the file with owner-only permissions.",
            ))
    elif kind == contract.CREDENTIAL_KIND_ENV:
        name = str(source.get("name") or "")
        status.update({"name": name, "present": bool(os.environ.get(name))})
        if not os.environ.get(name):
            issues.append(_issue(
                "error",
                "credential_env_missing",
                f"credential env var is unset: {name}",
                "Set the variable before running Yoke.",
            ))
    elif kind == contract.CREDENTIAL_KIND_AWS_SECRETS_MANAGER:
        status["present"] = True
    elif kind:
        issues.append(_issue(
            "error",
            "credential_kind_unknown",
            f"unsupported credential kind: {kind}",
        ))
    status["issues"] = issues
    return status


def _issue(severity: str, code: str, message: str, hint: str = "") -> dict[str, str]:
    item = {"severity": severity, "code": code, "message": message}
    if hint:
        item["hint"] = hint
    return item


__all__ = ["credential_status"]
