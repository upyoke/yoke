"""Environment and permission checks for product ``yoke status``."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from yoke_cli.config import machine_config
from yoke_contracts import owner_private_path
from yoke_contracts.machine_config import schema as contract

_WINDOWS = os.name == "nt"

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
    """Report a machine config that is not owner-only (or not owned by you)."""
    if not path.is_file() or owner_private_path.is_owner_private_file(path):
        return []
    message = f"{path} must be owned by you and private to your account"
    hint = (
        "Repair the file permissions so only your Windows account, SYSTEM "
        "and Administrators have access."
    )
    if not _WINDOWS:
        message += " (0600)"
        hint = f"As its owner, run `chmod 600 {path}`."
    return [
        {
            "severity": "error",
            "code": "config_permissions",
            "message": message,
            "hint": hint,
        }
    ]


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
