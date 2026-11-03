"""Executing-machine home context for session-cwd path authority."""

from __future__ import annotations

import os
from pathlib import Path


_FREE_PATH_SUFFIXES = (
    ".cache",
    "Library/Caches",
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
    ".yoke/playwright-cache",
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


def resembles_home_free_path(target: str) -> bool:
    """Recognize a possible home-free operand for diagnosis, never authority."""
    path = Path(target)
    if not path.is_absolute():
        return False
    # A candidate home must contain at least one component below the root.
    for home in path.parents:
        if home == Path(path.anchor):
            continue
        for suffix in _FREE_PATH_SUFFIXES:
            if path.is_relative_to(home / suffix):
                return True
    return False


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


__all__ = [
    "expand_machine_home",
    "home_free_path_prefixes",
    "resembles_home_free_path",
    "is_sanctioned_installed_read_path",
]
