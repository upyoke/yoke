"""Path-authority helpers for the session-cwd validator."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Iterable, List, Optional, Sequence

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
        "~/.codex/attachments",
        "~/.yoke/config.json",
    )
    out: list[str] = list(literals)
    home = os.path.expanduser("~")
    if home and home != "~":
        out.append(os.path.join(home, ".claude", "projects"))
        out.append(os.path.join(home, ".codex", "sessions"))
        out.append(os.path.join(home, ".codex", "archived_sessions"))
        out.append(os.path.join(home, ".codex", "attachments"))
        out.append(os.path.join(home, ".yoke", "config.json"))
    return tuple(out)


# Static free-path allowlist: OS temp dirs, discard devices, harness
# transcript/attachment stores, and the machine-config file no Yoke path
# claim should own. Watcher-minted capture paths under the live machine
# scratch root are allowlisted separately by
# :func:`is_yoke_watcher_capture_path` so ``dispatch-inputs`` and other
# scratch subtrees keep their own authority rules.
DEV_FAMILY_PREFIX = _abs("dev")

FREE_PATH_PREFIXES = (
    _abs("tmp"),
    _abs("private", "tmp"),
    _abs("var", "folders"),
    _abs("private", "var", "folders"),
    DEV_FAMILY_PREFIX,
    *_harness_internal_prefixes(),
)


_SANCTIONED_INSTALLED_READ_DIRS = (
    "~/.codex/plugins",
    "~/.codex/skills",
    "~/.claude/plugins",
    "~/.yoke/browser-runtime",
)

_SANCTIONED_INSTALLED_READ_FILES = (
    "~/.codex/AGENTS.md",
    "~/.local/bin/yoke",
    "~/.claude/settings.json",
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


def is_yoke_watcher_capture_path(
    target: str,
    *,
    scratch_root: str | None = None,
    session_id: str = "",
) -> bool:
    """True for a watcher capture under the selected machine/session root."""
    try:
        from yoke_core.domain.project_scratch_dir import global_scratch_root

        resolved = Path(resolve_for_display(target))
        root = (
            Path(scratch_root).expanduser().resolve()
            if scratch_root
            else global_scratch_root().resolve()
        )
        if not root.is_absolute() or root == Path(root.anchor):
            return False
        parts = resolved.relative_to(root).parts
    except Exception:
        return False
    if len(parts) < 7:
        return False
    if parts[1] != "sessions" or parts[3] != "runs":
        return False
    if parts[5] != "watcher-captures" or not parts[6:]:
        return False
    return not session_id or parts[2] == session_id


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


def is_dev_family_path(target: str) -> bool:
    """True for ``/dev/null`` and the rest of the ``/dev`` discard family."""
    return is_free_path(target, prefixes=(DEV_FAMILY_PREFIX,))


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
    active = FREE_PATH_PREFIXES if prefixes is None else prefixes
    for cand in candidates:
        for prefix in active:
            if cand == prefix or cand.startswith(prefix + os.sep):
                return True
        if prefixes is None and is_yoke_watcher_capture_path(cand):
            return True
    return False


def is_sanctioned_installed_read_path(target: str) -> bool:
    """True for an installed harness/tool path explicitly safe to read."""
    resolved = resolve_for_display(os.path.expanduser(target))
    for raw_dir in _SANCTIONED_INSTALLED_READ_DIRS:
        root = resolve_for_display(os.path.expanduser(raw_dir))
        if resolved == root or resolved.startswith(root + os.sep):
            return True

    files = list(_SANCTIONED_INSTALLED_READ_FILES)
    xdg_bin_home = os.environ.get("XDG_BIN_HOME", "").strip()
    if xdg_bin_home:
        files.append(os.path.join(xdg_bin_home, "yoke"))
    return any(
        resolved == resolve_for_display(os.path.expanduser(raw_file))
        for raw_file in files
    )


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
    """Walk held-claim worktree paths back to their repo roots.

    Lane-main-write uses this claim-scoped set so a live lane only
    guards its own project's main checkout.
    """
    _ = conn
    return _unique_repo_roots(c.worktree_path for c in claims)


def recorded_repo_roots(conn: Any) -> List[str]:
    """Repo roots named by every recorded lane, not only held claims.

    Session-cwd control-plane authorization uses this set so a claim in
    one project does not revoke other projects' checkouts. Relayed
    evaluation has no machine checkout map; recorded ``item_worktrees``
    paths are the authority that survives HTTPS.
    """
    from yoke_core.domain import db_backend
    from yoke_core.domain.schema_common import _table_exists

    if not _table_exists(conn, "item_worktrees"):
        return []
    try:
        rows = conn.execute(
            "SELECT path FROM item_worktrees WHERE path IS NOT NULL"
        ).fetchall()
    except db_backend.operational_error_types(conn):
        return []
    paths: List[str] = []
    for row in rows:
        value = row["path"] if hasattr(row, "keys") else row[0]
        text = str(value or "").strip()
        if text:
            paths.append(text)
    return _unique_repo_roots(paths)


def repo_root_from_worktree_path(worktree_path: str) -> Optional[str]:
    parts = Path(worktree_path).parts
    for idx in range(len(parts) - 1, 0, -1):
        if parts[idx] == ".worktrees":
            return str(Path(*parts[:idx]))
    return None


def _unique_repo_roots(worktree_paths: Iterable[str]) -> List[str]:
    seen: set[str] = set()
    out: List[str] = []
    for worktree_path in worktree_paths:
        root = repo_root_from_worktree_path(worktree_path)
        if root and root not in seen:
            seen.add(root)
            out.append(root)
    return out


__all__ = [
    "DEV_FAMILY_PREFIX",
    "FREE_PATH_PREFIXES",
    "TOOL_DIR_PREFIXES",
    "derive_repo_roots",
    "is_dev_family_path",
    "is_free_path",
    "is_inside",
    "is_inside_control_plane",
    "is_sanctioned_installed_read_path",
    "is_under_tool_dir",
    "is_yoke_watcher_capture_path",
    "recorded_repo_roots",
    "resolve_for_display",
]
