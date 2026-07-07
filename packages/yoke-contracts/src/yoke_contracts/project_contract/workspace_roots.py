"""Workspace-root resolution shared by product clients and core tools."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Callable, Optional

BOUND_WORKSPACE_ENV_VAR = "YOKE_BOUND_WORKSPACE"
RENDER_TARGET_ROOT_ENV_VAR = "YOKE_RENDER_TARGET_ROOT"


def _repo_root() -> Path:
    """Resolve the repo root via git, then a ``Path(__file__)`` walk-up."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        )
        return Path(result.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    p = Path(__file__).resolve()
    while p != p.parent:
        if (p / "runtime" / "agents").is_dir():
            return p
        p = p.parent
    raise RuntimeError("Cannot determine repo root")


def _is_inside_linked_worktree(start: Optional[Path] = None) -> bool:
    """Detect whether ``start`` (default: cwd) is inside a linked git worktree."""
    cwd = str(start) if start is not None else None
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            capture_output=True,
            text=True,
            check=True,
            cwd=cwd,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False
    common_dir = result.stdout.strip()
    if not common_dir:
        return False
    return common_dir != ".git"


def resolve_target_root_for_cli(
    arg_value: Optional[str] = None,
    *,
    env_var: str = RENDER_TARGET_ROOT_ENV_VAR,
    repo_root: Callable[[], Path] = _repo_root,
    is_inside_linked_worktree: Callable[[], bool] = _is_inside_linked_worktree,
) -> Path:
    """Resolve ``target_root`` from CLI arg, env var, or repo-root fallback."""
    if arg_value:
        return Path(arg_value).resolve()
    env_value = os.environ.get(env_var, "").strip()
    if env_value:
        return Path(env_value).resolve()
    if is_inside_linked_worktree():
        raise RuntimeError(
            "agents_render: refusing implicit cwd-based target_root from a "
            "linked worktree. Pass --target-root <path> or set "
            f"${env_var}=<path> to name the checkout that should receive "
            "the rendered substrate."
        )
    return repo_root().resolve()


__all__ = [
    "BOUND_WORKSPACE_ENV_VAR",
    "RENDER_TARGET_ROOT_ENV_VAR",
    "_is_inside_linked_worktree",
    "_repo_root",
    "resolve_target_root_for_cli",
]
