"""Resolve a live checkout root for Cursor hook subprocesses.

Cursor may keep ``CURSOR_PROJECT_DIR`` / ``workspace_roots`` pointed at a
linked worktree after that directory is removed. Project ``stop`` hooks
then either fail to spawn (cwd missing) or export a dead ``YOKE_ROOT``.
This helper picks the first existing candidate and, when a path sits under
a missing ``.worktrees/<lane>`` (or Claude ``.claude/worktrees/<lane>``),
falls back to the parent checkout that still exists.
"""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath
from typing import Iterable, Optional


def parent_checkout_if_missing_worktree(path: str) -> str:
    """Return the repo root above a missing linked-worktree path, else ``\"\"``."""
    if not path:
        return ""
    parts = PurePosixPath(path.replace("\\", "/")).parts
    for marker in (".worktrees", "worktrees"):
        try:
            idx = parts.index(marker)
        except ValueError:
            continue
        if marker == "worktrees" and (idx == 0 or parts[idx - 1] != ".claude"):
            continue
        if idx == 0:
            continue
        parent = str(Path(*parts[:idx]))
        if parent and os.path.isdir(parent):
            return parent
    return ""


def resolve_existing_hook_root(
    *candidates: Optional[str],
    fallback: Optional[str] = None,
) -> str:
    """Return the first existing directory among *candidates*, with peel fallback.

    Empty strings and non-directories are skipped. When a candidate names a
    missing linked worktree, the parent checkout is tried next for that
    candidate before moving on. *fallback* (default ``$HOME`` then ``/tmp``)
    is used only when nothing else exists.
    """
    for raw in candidates:
        if not isinstance(raw, str) or not raw:
            continue
        if os.path.isdir(raw):
            return raw
        peeled = parent_checkout_if_missing_worktree(raw)
        if peeled:
            return peeled
    if fallback is not None:
        return fallback if fallback and os.path.isdir(fallback) else ""
    home = os.environ.get("HOME") or ""
    if home and os.path.isdir(home):
        return home
    return "/tmp" if os.path.isdir("/tmp") else ""


def resolve_existing_hook_root_from_env(
    env: Optional[Iterable[tuple[str, str]]] = None,
) -> str:
    """Resolve from ``YOKE_ROOT``, ``CURSOR_PROJECT_DIR``, then ``PWD``."""
    mapping = dict(env) if env is not None else os.environ
    return resolve_existing_hook_root(
        mapping.get("YOKE_ROOT"),
        mapping.get("CURSOR_PROJECT_DIR"),
        mapping.get("PWD"),
    )


__all__ = [
    "parent_checkout_if_missing_worktree",
    "resolve_existing_hook_root",
    "resolve_existing_hook_root_from_env",
]
