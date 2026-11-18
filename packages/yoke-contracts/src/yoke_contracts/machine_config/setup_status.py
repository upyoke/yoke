"""Shared `yoke status` answers for an unset-up machine and a non-git folder."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

MACHINE_NOT_SET_UP = "machine_not_set_up"


def not_set_up_issue(config_path: Path) -> dict[str, str]:
    """The one issue an unset-up machine reports: `yoke setup` writes the rest."""
    return {
        "severity": "error",
        "code": MACHINE_NOT_SET_UP,
        "message": f"this machine is not set up: no machine config at {config_path}",
        "hint": "Run `yoke setup`.",
    }


def is_git_checkout(folder: Path) -> bool:
    return (folder / ".git").exists()


def folder_line(report: Mapping[str, Any]) -> str:
    """Only a folder with `.git` is a checkout; name any other folder as one."""
    root = report.get("repo_root")
    if report.get("repo_is_git_checkout"):
        return f"  checkout: {root}"
    return f"  folder: {root} (not a git checkout)"


__all__ = ["MACHINE_NOT_SET_UP", "folder_line", "is_git_checkout", "not_set_up_issue"]
