"""Non-secret credential-presence facts for the machine heartbeat."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from yoke_contracts.machine_config.capability_secrets import (
    AWS_ADMIN_CAPABILITY,
    AWS_ADMIN_SECRET_KEYS,
    CAPABILITY_SECRETS_DIR_NAME,
)
from yoke_contracts.session_control.plan_limits import reading_is_ok


def _aws_present(secret_root: Path) -> bool:
    capability_root = secret_root / CAPABILITY_SECRETS_DIR_NAME
    if not capability_root.is_dir():
        return False
    required = {"access_key_id", "secret_access_key"} & AWS_ADMIN_SECRET_KEYS
    return any(
        all((directory / key).is_file() for key in required)
        for directory in capability_root.glob(f"*/{AWS_ADMIN_CAPABILITY}")
        if directory.is_dir()
    )


def _harness_presence(
    versions: Mapping[str, Any], plan_limits: Mapping[str, Any]
) -> dict[str, bool]:
    return {
        surface: bool(
            surface in versions
            and isinstance(plan_limits.get(surface), Mapping)
            and reading_is_ok(plan_limits[surface])
        )
        for surface in ("claude-cli", "codex-cli", "cursor-cli")
    }


def observe_credential_presence(
    config: Mapping[str, Any],
    *,
    versions: Mapping[str, Any],
    plan_limits: Mapping[str, Any],
    secret_root: Path,
) -> dict[str, Any]:
    """Publish booleans only; never read or transmit credential material."""
    github = config.get("github")
    authorization = github.get("authorization") if isinstance(github, Mapping) else None
    return {
        "github": bool(
            isinstance(authorization, Mapping)
            and authorization.get("status") == "authorized"
            and authorization.get("refresh_credential_ref")
        ),
        "aws": _aws_present(secret_root),
        "harnesses": _harness_presence(versions, plan_limits),
    }


__all__ = ["observe_credential_presence"]
