"""Path-authority helpers for the session-cwd validator."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, List, Optional, Sequence

from yoke_core.domain.session_claimed_worktrees import ClaimedWorktree

_ROOT = "/"


def _abs(*parts: str) -> str:
    return os.path.join(_ROOT, *parts)


def _harness_internal_prefixes() -> tuple[str, ...]:
    """Expand harness-internal artifact directories under ``$HOME``."""
    literals = (
        "~/.claude/projects",
        "~/.codex/sessions",
        "~/.codex/archived_sessions",
    )
    out: list[str] = list(literals)
    home = os.path.expanduser("~")
    if home and home != "~":
        out.append(os.path.join(home, ".claude", "projects"))
        out.append(os.path.join(home, ".codex", "sessions"))
        out.append(os.path.join(home, ".codex", "archived_sessions"))
    return tuple(out)


# Free-path allowlist: scratch dirs, discard devices, and harness
# transcript stores no Yoke path claim should own.
FREE_PATH_PREFIXES = (
    _abs("tmp"),
    _abs("private", "tmp"),
    _abs("var", "folders"),
    _abs("private", "var", "folders"),
    _abs("dev"),
    *_harness_internal_prefixes(),
)


# Standard tool / system binary directories. An extracted target under one
# of these is an EXECUTED binary, not a write target.
TOOL_DIR_PREFIXES = (
    _abs("opt", "homebrew", "bin"),
    _abs("opt", "homebrew", "sbin"),
    _abs("opt", "homebrew", "Cellar"),
    _abs("opt", "homebrew", "opt"),
    _abs("usr", "local", "bin"),
    _abs("usr", "local", "sbin"),
    _abs("usr", "bin"),
    _abs("usr", "sbin"),
    _abs("bin"),
    _abs("sbin"),
)


def is_under_tool_dir(
    target: str,
    *,
    prefixes: Sequence[str] | None = None,
) -> bool:
    """Return True when ``target`` resolves under a standard tool directory."""
    resolved = resolve_for_display(target)
    for prefix in prefixes if prefixes is not None else TOOL_DIR_PREFIXES:
        if resolved == prefix or resolved.startswith(prefix + os.sep):
            return True
    return False


def is_free_path(
    target: str,
    *,
    prefixes: Sequence[str] | None = None,
) -> bool:
    """Return True when ``target`` lands under a free-path prefix."""
    candidates = {resolve_for_display(target)}
    expanded = os.path.expanduser(target)
    if expanded != target:
        candidates.add(resolve_for_display(expanded))
    for cand in candidates:
        for prefix in prefixes if prefixes is not None else FREE_PATH_PREFIXES:
            if cand == prefix or cand.startswith(prefix + os.sep):
                return True
    return False


def is_inside(target: str, root: str) -> bool:
    """``target`` is the same path as ``root`` or under it."""
    if not target or not root:
        return False
    try:
        t = str(Path(target).resolve())
        r = str(Path(root).resolve())
    except OSError:
        return False
    if t == r:
        return True
    return t.startswith(r + os.sep)


def is_inside_control_plane(target: str, repo_root: str) -> bool:
    """Return true for project control-plane paths outside ``.worktrees``."""
    if not is_inside(target, repo_root):
        return False
    try:
        r = Path(repo_root).resolve()
        t = str(Path(target).resolve())
    except OSError:
        return False
    worktrees_dir = str(r / ".worktrees")
    if t == worktrees_dir or t.startswith(worktrees_dir + os.sep):
        return False
    return True


def resolve_for_display(target: str) -> str:
    try:
        return str(Path(target).resolve())
    except OSError:
        return target


def derive_repo_roots(
    conn: Any,
    claims: Sequence[ClaimedWorktree],
) -> List[str]:
    """Walk a claim's worktree path back to its repo root."""
    _ = conn
    seen: set[str] = set()
    out: List[str] = []
    for claim in claims:
        root = repo_root_from_worktree_path(claim.worktree_path)
        if root and root not in seen:
            seen.add(root)
            out.append(root)
    return out


def repo_root_from_worktree_path(worktree_path: str) -> Optional[str]:
    parts = Path(worktree_path).parts
    for idx in range(len(parts) - 1, 0, -1):
        if parts[idx] == ".worktrees":
            return str(Path(*parts[:idx]))
    return None


__all__ = [
    "FREE_PATH_PREFIXES",
    "TOOL_DIR_PREFIXES",
    "derive_repo_roots",
    "is_free_path",
    "is_inside",
    "is_inside_control_plane",
    "is_under_tool_dir",
    "resolve_for_display",
]
