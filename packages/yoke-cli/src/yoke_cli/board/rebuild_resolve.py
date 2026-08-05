"""Resolve the board rebuild checkout and BOARD.md path."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from yoke_cli.config import machine_config
from yoke_cli.config.checkout_context import _strip_worktree_path
from yoke_contracts.machine_config.schema import DEFAULT_BOARD_PATH


class BoardProjectResolutionError(RuntimeError):
    """No unique machine-configured project checkout could be resolved."""


def _normalized_path(path: Path) -> Path:
    selected = Path(_strip_worktree_path(str(path.expanduser())))
    try:
        return selected.resolve()
    except OSError:
        return selected


def _contains(parent: Path, child: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _configured_project_matches(start: Path) -> list[machine_config.ConfiguredProject]:
    selected = _normalized_path(start.parent if start.is_file() else start)
    matches: list[machine_config.ConfiguredProject] = []
    for project in machine_config.configured_projects(existing_only=True):
        checkout = _normalized_path(project.checkout)
        if _contains(checkout, selected):
            matches.append(project)
    return sorted(
        matches,
        key=lambda project: len(_normalized_path(project.checkout).parts),
        reverse=True,
    )


def _configured_projects() -> list[machine_config.ConfiguredProject]:
    return machine_config.configured_projects(existing_only=True)


def _matching_configured_project_root(start: Path) -> Path | None:
    matches = _configured_project_matches(start)
    if matches:
        return _normalized_path(matches[0].checkout)
    return None


def _resolve_configured_project(start: Path, *, explicit: bool) -> Path:
    match = _matching_configured_project_root(start)
    if match is not None:
        return match
    projects = _configured_projects()
    if explicit:
        raise BoardProjectResolutionError(
            f"{start.expanduser()} is not inside a project registered in "
            "machine config; run from a registered checkout or pass one with "
            "--repo-root."
        )
    if len(projects) == 1:
        return _normalized_path(projects[0].checkout)
    if not projects:
        raise BoardProjectResolutionError(
            "no projects are registered in machine config; run `yoke onboard` "
            "or `yoke project register` first."
        )
    configured = ", ".join(
        str(_normalized_path(project.checkout)) for project in projects
    )
    raise BoardProjectResolutionError(
        "could not choose a board project from this directory; run from inside "
        f"one registered checkout or pass --repo-root. Configured projects: {configured}"
    )


def resolve_main_repo_root(repo_arg: Optional[str] = None) -> Path:
    if repo_arg:
        return _resolve_configured_project(Path(repo_arg), explicit=True)

    env_value = os.environ.get("CLAUDE_PROJECT_DIR")
    if env_value:
        match = _matching_configured_project_root(Path(env_value))
        if match is not None:
            return match

    return _resolve_configured_project(Path.cwd(), explicit=False)


def resolve_board_path(repo_root: Path, output_name: Optional[str] = None) -> Path:
    """Return the fixed checkout-relative board path (``.yoke/BOARD.md``)."""

    default = repo_root / DEFAULT_BOARD_PATH
    if not output_name:
        return default
    selected = Path(output_name).expanduser()
    if selected.is_absolute():
        return selected
    if len(selected.parts) == 1:
        return default.with_name(output_name)
    return repo_root / selected


__all__ = [
    "BoardProjectResolutionError",
    "resolve_board_path",
    "resolve_main_repo_root",
]
