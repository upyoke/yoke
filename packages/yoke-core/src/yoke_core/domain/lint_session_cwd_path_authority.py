"""Path-authority helpers for the session-cwd validator."""

from __future__ import annotations

import os
import posixpath
from pathlib import Path, PurePosixPath
from yoke_contracts.hook_runner.bash_paths import (
    canonical_native_path, is_absolute,
    resolve_bash_path,
    windows_path,
    is_under,
)
from typing import Any, Iterable, List, Optional, Sequence

from yoke_contracts.hook_runner.repo_paths import normalize_repo_path
from yoke_contracts.free_paths import (
    DEV_FAMILY_PREFIX,
    STATIC_FREE_PATH_PREFIXES as _STATIC_FREE_PATH_PREFIXES,
    free_path_prefixes as machine_free_path_prefixes,
)
from yoke_core.domain.lint_session_cwd_home import (
    expand_machine_home,
    home_free_path_prefixes,
)
from yoke_core.domain.session_claimed_worktrees import ClaimedWorktree

# The free-path allowlist (OS temp dirs, absolute TMPDIR, and discard family) is
# shared with every writer that must choose a destination the guard will
# admit, so it lives in ``yoke_contracts.free_paths``. Harness
# transcript/attachment stores and the machine-config file are added here
# per executing machine by ``home_free_path_prefixes``. Watcher-minted
# capture paths under the live machine scratch root are allowlisted
# separately by :func:`is_yoke_watcher_capture_path` so ``dispatch-inputs``
# and other scratch subtrees keep their own authority rules.


def free_path_prefixes(machine_home: str | None = None) -> tuple[str, ...]:
    """Resolve free paths against the local or explicitly evidenced home.

    Resolved per call: the home and ``TMPDIR`` belong to the command being
    judged, not to whatever environment first imported this module.
    """
    return (
        *machine_free_path_prefixes(_STATIC_FREE_PATH_PREFIXES),
        *home_free_path_prefixes(machine_home),
    )


def is_yoke_watcher_capture_path(
    target: str,
    *,
    scratch_root: str | None = None,
    session_id: str = "",
) -> bool:
    """True for a watcher capture under the selected machine/session root.

    ``scratch_root=None`` selects this process's own scratch root, for an
    in-process caller on the writing machine; a hook passes the client's
    scratch-root fact, and ``""`` (no fact) matches nothing.
    """
    if scratch_root == "":
        return False
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


def is_dev_family_path(target: str) -> bool:
    """True for ``/dev/null`` and the rest of the ``/dev`` discard family."""
    if not is_absolute(target):
        return False
    if target.startswith("/dev/") or target == "/dev":
        normalized = posixpath.normpath(target)
        return normalized == "/dev" or normalized.startswith("/dev/")
    return is_free_path(target, prefixes=(resolve_bash_path(DEV_FAMILY_PREFIX),))


def is_free_path(
    target: str,
    *,
    prefixes: Sequence[str] | None = None,
    machine_home: str | None = None,
) -> bool:
    """Return True when ``target`` lands under a free-path prefix."""
    candidates = {resolve_for_display(target, machine_home=machine_home)}
    active = free_path_prefixes(machine_home) if prefixes is None else prefixes
    for cand in candidates:
        for prefix in active:
            prefix = resolve_bash_path(prefix)
            if cand == prefix or cand.startswith(
                prefix.rstrip("/\\")
                + ("/" if windows_path(cand) and os.name != "nt" else os.sep)
            ):
                return True
        if prefixes is None and is_yoke_watcher_capture_path(cand):
            return True
    return False


def is_inside(target: str, root: str) -> bool:
    """``target`` is the same path as ``root`` or under it."""
    return is_under(target, root)


def is_inside_control_plane(target: str, repo_root: str) -> bool:
    """Return true for project control-plane paths outside ``.worktrees``."""
    if not is_inside(target, repo_root):
        return False
    from yoke_contracts.hook_runner.bash_paths import join_path

    return not is_inside(target, join_path(repo_root, ".worktrees"))


def outside_worktree_lanes(
    targets: Sequence[str],
    repo_roots: Sequence[str],
) -> List[str]:
    """Drop targets landing inside any repo root's ``.worktrees`` subtree.

    The complement of :func:`is_inside_control_plane`: that predicate
    answers "is this a checkout path outside every lane?", this one
    selects the targets no lane contains.
    """
    from yoke_contracts.hook_runner.bash_paths import join_path

    lanes = [join_path(root, ".worktrees") for root in repo_roots]
    return [t for t in targets if not any(is_inside(t, lane) for lane in lanes)]


def resolve_for_display(target: str, *, machine_home: str | None = None) -> str:
    try:
        expanded = expand_machine_home(target, machine_home=machine_home)
        return resolve_bash_path(expanded)
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
            "SELECT DISTINCT COALESCE(NULLIF(substring(btrim(path) FROM "
            "'^(.*)/[.]worktrees(?:/.*)?$'), ''), '/') AS repo_root "
            "FROM item_worktrees "
            "WHERE btrim(path) ~ '^.*/[.]worktrees(?:/.*)?$' "
            "ORDER BY repo_root"
        ).fetchall()
    except db_backend.operational_error_types(conn):
        return []
    paths: List[str] = []
    for row in rows:
        value = row["repo_root"] if hasattr(row, "keys") else row[0]
        text = str(value or "").strip()
        if text:
            paths.append(text)
    return sorted({normalize_repo_path(root) for root in paths})


def repo_root_from_worktree_path(worktree_path: str) -> Optional[str]:
    normalized = normalize_repo_path(canonical_native_path(worktree_path))
    root, marker, _ = normalized.rpartition("/.worktrees/")
    if marker:
        return root or "/"
    if normalized.endswith("/.worktrees"):
        return normalized.removesuffix("/.worktrees") or "/"
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
    "derive_repo_roots",
    "free_path_prefixes",
    "is_dev_family_path",
    "is_free_path",
    "is_inside",
    "is_inside_control_plane",
    "is_yoke_watcher_capture_path",
    "outside_worktree_lanes",
    "recorded_repo_roots",
    "resolve_for_display",
]
