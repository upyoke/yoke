"""Environment and permission checks for product ``yoke status``."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from yoke_cli.config import machine_config
from yoke_contracts.machine_config import schema as contract

SECRET_ENV_KEYS = {"YOKE_PG_DSN"}
AMBIENT_ENV_KEYS = (
    machine_config.CONFIG_FILE_ENV,
    machine_config.HOME_ENV,
    contract.ENV_OVERRIDE,
    "YOKE_PROJECT",
    "YOKE_PG_DSN",
    "YOKE_PG_DSN_FILE",
    "YOKE_SCRATCH_ROOT",
    "YOKE_CONNECTED_ENV_DISABLE",
)


def permission_issues(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    stat = path.stat()
    issues: list[dict[str, str]] = []
    if stat.st_mode & 0o077:
        issues.append(
            {
                "severity": "error",
                "code": "config_permissions",
                "message": f"{path} must be owner-only (0600)",
                "hint": f"Run `chmod 600 {path}`.",
            }
        )
    if hasattr(os, "getuid") and stat.st_uid != os.getuid():
        issues.append(
            {
                "severity": "error",
                "code": "config_owner",
                "message": f"{path} is not owned by the current user",
            }
        )
    return issues


def ambient_env_status() -> dict[str, Any]:
    data = {}
    for key in AMBIENT_ENV_KEYS:
        raw = os.environ.get(key)
        data[key] = {
            "set": raw is not None,
            "value": "<redacted>" if key in SECRET_ENV_KEYS and raw else (raw or ""),
        }
    return data


__all__ = ["ambient_env_status", "permission_issues"]
