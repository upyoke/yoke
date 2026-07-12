"""Saved GitHub App connection routing for the onboarding wizard."""

from __future__ import annotations

from typing import Any, Protocol

from yoke_cli.config import machine_config


class _Shell(Protocol):  # pragma: no cover - structural typing only
    result: Any
    _stored_github_attempted: bool

    def _check_machine_github(self, *, reuse: bool) -> None: ...


def connection_exists(config_path: Any) -> bool:
    """Whether machine config already carries a GitHub connection."""

    return bool(machine_config.github_config(config_path))


def auto_recheck_authorized(shell: _Shell) -> None:
    """Revalidate one saved authorization while preserving the choice history."""

    if shell._stored_github_attempted:
        return
    try:
        github = machine_config.github_config(shell.result.config_path)
    except (OSError, RuntimeError, ValueError):
        return
    authorization = github.get("authorization")
    if not (
        isinstance(authorization, dict)
        and authorization.get("status") == "authorized"
    ):
        return
    shell._stored_github_attempted = True
    shell._check_machine_github(reuse=True)


__all__ = ["auto_recheck_authorized", "connection_exists"]
