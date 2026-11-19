"""Shared `yoke status` answers for an unset-up machine and a non-git folder."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

from yoke_contracts.api.function_call import FunctionError
from yoke_contracts.control_plane_locality import PG_DSN_ENV, PG_DSN_FILE_ENV
from yoke_contracts.machine_config.paths import config_path
from yoke_contracts.machine_config.schema_github import has_github_config

MACHINE_NOT_SET_UP = "machine_not_set_up"
SETUP_HINT = "Run `yoke setup`."
#: Code prefix of the native Windows preflight verdicts.
NATIVE_PREFLIGHT_PREFIX = "windows_"
#: An explicit database authority in the environment (a lane, CI, a hosted
#: tenant) stands in for setup's connection.
DATABASE_AUTHORITY_ENVS = (PG_DSN_ENV, PG_DSN_FILE_ENV, "YOKE_DB_SECRET_ARN")


def is_set_up(payload: Mapping[str, Any]) -> bool:
    """Setup names a connection or GitHub access; the installer's file has neither."""
    connections = payload.get("connections")
    return bool(isinstance(connections, Mapping) and connections) or has_github_config(
        payload
    )


def not_set_up_issue(config_path: Path) -> dict[str, str]:
    """The one issue an unset-up machine reports: `yoke setup` writes the rest."""
    return {
        "severity": "error",
        "code": MACHINE_NOT_SET_UP,
        "message": (
            f"this machine is not set up: {config_path} names no connection"
        ),
        "hint": SETUP_HINT,
    }


def setup_blocking(issues: Iterable[Mapping[str, str]]) -> list[dict[str, str]]:
    """Drop native-preflight warning and info rows from an unset-up report.

    Only the error verdicts would refuse `yoke setup`; setup itself prints
    every verdict, so the rest would bury its one answer.
    """
    return [
        dict(issue)
        for issue in issues
        if not str(issue.get("code", "")).startswith(NATIVE_PREFLIGHT_PREFIX)
        or issue.get("severity") == "error"
    ]


def not_set_up_error(
    payload: Mapping[str, Any], environ: Mapping[str, str]
) -> Optional[FunctionError]:
    """The refusal for an engine call on an unset-up machine, or None.

    Without setup the in-process engine has no database to reach; naming
    `yoke setup` beats a raw DSN error from deep inside the engine.
    """
    if is_set_up(payload):
        return None
    if any(str(environ.get(name, "")).strip() for name in DATABASE_AUTHORITY_ENVS):
        return None
    return FunctionError(
        code=MACHINE_NOT_SET_UP,
        message=(
            f"this machine is not set up: {config_path()} names no connection, "
            "so Yoke has no control plane to run this command against"
        ),
        recovery_hint=SETUP_HINT,
    )


def is_git_checkout(folder: Path) -> bool:
    return (folder / ".git").exists()


def folder_line(report: Mapping[str, Any]) -> str:
    """Only a folder with `.git` is a checkout; name any other folder as one."""
    root = report.get("repo_root")
    if report.get("repo_is_git_checkout"):
        return f"  checkout: {root}"
    return f"  folder: {root} (not a git checkout)"


__all__ = [
    "DATABASE_AUTHORITY_ENVS",
    "MACHINE_NOT_SET_UP",
    "NATIVE_PREFLIGHT_PREFIX",
    "SETUP_HINT",
    "folder_line",
    "is_git_checkout",
    "is_set_up",
    "not_set_up_error",
    "not_set_up_issue",
    "setup_blocking",
]
