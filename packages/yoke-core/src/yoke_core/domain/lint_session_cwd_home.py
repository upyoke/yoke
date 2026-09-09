"""Executing-machine home context for session-cwd path authority."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Sequence


_FREE_PATH_SUFFIXES = (
    ".claude/projects",
    ".codex/sessions",
    ".codex/archived_sessions",
    ".codex/attachments",
    ".yoke/config.json",
)

_SANCTIONED_READ_DIR_SUFFIXES = (
    ".codex/plugins",
    ".codex/skills",
    ".claude/plugins",
    ".yoke/browser-runtime",
    ".yoke/relay-instances",
    ".local/bin",
)

_SANCTIONED_READ_FILE_SUFFIXES = (
    ".codex/AGENTS.md",
    ".local/bin/yoke",
    ".claude/settings.json",
    ".cursor/hooks.json",
)


def _selected_home(machine_home: str | None) -> str:
    if machine_home is None:
        expanded = os.path.expanduser("~")
        return "" if expanded == "~" else str(Path(expanded).resolve())
    return machine_home


def expand_machine_home(target: str, *, machine_home: str | None) -> str:
    """Expand only the current user's tilde against the selected home."""
    home = _selected_home(machine_home)
    if not home:
        return target
    if target == "~":
        return home
    if target.startswith("~/"):
        return str(Path(home, target[2:]))
    return target


def home_free_path_prefixes(machine_home: str | None = None) -> tuple[str, ...]:
    """Return home-derived free paths for the machine executing the command."""
    home = _selected_home(machine_home)
    if not home:
        return ()
    resolved = tuple(str(Path(home, suffix)) for suffix in _FREE_PATH_SUFFIXES)
    if machine_home is None:
        return (*(f"~/{suffix}" for suffix in _FREE_PATH_SUFFIXES), *resolved)
    return resolved


def is_sanctioned_installed_read_path(
    target: str,
    *,
    machine_home: str | None = None,
) -> bool:
    """True for an installed harness/tool path explicitly safe to read."""
    home = _selected_home(machine_home)
    if not home:
        return False
    resolved = str(Path(expand_machine_home(target, machine_home=home)).resolve())
    for suffix in _SANCTIONED_READ_DIR_SUFFIXES:
        root = str(Path(home, suffix).resolve())
        if resolved == root or resolved.startswith(root + os.sep):
            return True
    files = [
        str(Path(home, suffix).resolve()) for suffix in _SANCTIONED_READ_FILE_SUFFIXES
    ]
    if machine_home is None:
        xdg_bin_home = os.environ.get("XDG_BIN_HOME", "").strip()
        if xdg_bin_home:
            files.append(str(Path(xdg_bin_home, "yoke").resolve()))
    return resolved in files


def is_external_reference_path(
    target: str,
    *,
    repo_roots: Sequence[str],
    machine_home: str | None = None,
) -> bool:
    """True for ordinary material under the selected home, outside checkouts."""
    home = _selected_home(machine_home)
    if not home:
        return False
    resolved = str(Path(expand_machine_home(target, machine_home=home)).resolve())
    if not _is_inside(resolved, home):
        return False
    relative = Path(resolved).parts[len(Path(home).parts) :]
    if not relative or relative[0].startswith(".") or ".worktrees" in relative:
        return False
    return not any(_is_inside(resolved, root) for root in repo_roots)


def _is_inside(target: str, root: str) -> bool:
    try:
        resolved_target = str(Path(target).resolve())
        resolved_root = str(Path(root).resolve())
    except OSError:
        return False
    return resolved_target == resolved_root or resolved_target.startswith(
        resolved_root + os.sep
    )


__all__ = [
    "expand_machine_home",
    "home_free_path_prefixes",
    "is_external_reference_path",
    "is_sanctioned_installed_read_path",
]
