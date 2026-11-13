"""Folders under the managed lane roots that git no longer registers.

A lane's registration can go while its folder stays — a hand-run
``git worktree remove`` that stopped early, a tool that rebuilt output into a
lane after it was retired, an ad-hoc ``mkdir``. Such a folder holds no work
when every path in it is ignored by the main checkout's own rules: build
output like ``.next/`` or ``node_modules/`` is the usual case. This module
finds those folders and retires them through a tombstone
(:func:`yoke_core.engines.worktree_removal.remove_stray_folder`); a folder
holding any path the rules do not ignore is kept and named with that path.

It asks git only, never the control plane: the folder list is read first and
the registry after it, so a lane registered while the sweep runs is never
taken for a stray. Tombstones and empty folders are left alone — the first
belongs to ``finish_tombstones``, the second costs nothing.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from yoke_core.engines.git_worktree_registry import registered_worktrees
from yoke_core.engines.worktree_removal import (
    GIT_TIMEOUT_S,
    MANAGED_ROOTS,
    TOMBSTONE_PREFIX,
    remove_stray_folder,
)


@dataclass(frozen=True)
class StrayFolder:
    """One unregistered managed folder and what became of it."""

    path: Path
    first_unignored: str = ""
    removed: bool = False
    reason: str = ""

    @property
    def disposable(self) -> bool:
        return not self.reason


class _CheckIgnoreFailed(Exception):
    pass


def _ignored(repo_root: Path, candidates: list[str]) -> set[str]:
    """Which candidate paths the main checkout's ignore rules match."""
    payload = "".join(f"{path}\0" for path in candidates).encode()
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(repo_root),
                "check-ignore",
                "--no-index",
                "--stdin",
                "-z",
            ],
            input=payload,
            capture_output=True,
            timeout=GIT_TIMEOUT_S,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise _CheckIgnoreFailed(str(exc)) from exc
    if result.returncode not in (0, 1):
        detail = result.stderr.decode(errors="replace").strip()
        raise _CheckIgnoreFailed(detail or f"exit {result.returncode}")
    return {path for path in result.stdout.decode().split("\0") if path}


def first_unignored_path(repo_root: str | Path, folder: str | Path) -> str:
    """The first path in *folder* the main checkout does not ignore, or ``""``.

    Walks top-down one level at a time, asking about every entry of a level in
    one ``check-ignore`` call, and never descends into an ignored directory.
    Raises ``_CheckIgnoreFailed`` when git cannot answer.
    """
    repo = Path(repo_root)
    base = Path(folder)
    level = [""]
    while level:
        candidates: list[str] = []
        directories: list[str] = []
        for relative in level:
            with os.scandir(base / relative) as entries:
                for entry in sorted(entries, key=lambda item: item.name):
                    if entry.name == ".git":
                        continue
                    path = f"{relative}{entry.name}"
                    if entry.is_dir(follow_symlinks=False):
                        candidates.append(f"{path}/")
                        directories.append(f"{path}/")
                    else:
                        candidates.append(path)
        if not candidates:
            return ""
        ignored = _ignored(repo, candidates)
        for path in candidates:
            if path not in ignored and path not in directories:
                return path
        level = [path for path in directories if path not in ignored]
    return ""


def _managed_folders(repo_root: Path) -> list[Path]:
    found: list[Path] = []
    for managed in MANAGED_ROOTS:
        root = repo_root / managed
        if not root.is_dir():
            continue
        for child in sorted(root.iterdir()):
            if child.name.startswith(TOMBSTONE_PREFIX) or child.is_symlink():
                continue
            if child.is_dir() and any(child.iterdir()):
                found.append(child.resolve())
    return found


def assess_stray_folders(
    repo_root: str | Path, run_git: Callable[..., Any]
) -> list[StrayFolder] | None:
    """Every unregistered, non-empty managed folder, judged without changes.

    ``None`` means the registry could not be read, so nothing is claimed.
    """
    root = Path(repo_root).resolve()
    folders = _managed_folders(root)
    if not folders:
        return []
    entries = registered_worktrees(run_git, str(root))
    if entries is None:
        return None
    registered = {Path(entry.path).resolve() for entry in entries}
    found: list[StrayFolder] = []
    for folder in folders:
        if folder in registered:
            continue
        try:
            first = first_unignored_path(root, folder)
        except (_CheckIgnoreFailed, OSError) as exc:
            found.append(StrayFolder(folder, reason=f"ignore rules unreadable: {exc}"))
            continue
        if first:
            found.append(
                StrayFolder(
                    folder,
                    first_unignored=first,
                    reason=f"unregistered folder holds a non-ignored path: {first}",
                )
            )
        else:
            found.append(StrayFolder(folder))
    return found


def prune_stray_folders(
    repo_root: str | Path, run_git: Callable[..., Any]
) -> list[StrayFolder]:
    """Remove every stray folder that holds only ignored files; report the rest."""
    found = assess_stray_folders(repo_root, run_git)
    if found is None:
        return []
    results: list[StrayFolder] = []
    for stray in found:
        if not stray.disposable:
            results.append(stray)
            continue
        removal = remove_stray_folder(repo_root, stray.path)
        if removal.removed:
            results.append(StrayFolder(stray.path, removed=True, reason=removal.reason))
        else:
            results.append(StrayFolder(stray.path, reason=removal.reason))
    return results


__all__ = [
    "StrayFolder",
    "assess_stray_folders",
    "first_unignored_path",
    "prune_stray_folders",
]
