"""Fail-closed pruning for DB-owned merged worktrees and branches."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from yoke_contracts.lifecycle_status import TASK_TERMINAL_SUCCESS
from yoke_core.domain import db_backend


_ITEM_TERMINAL = frozenset({"done", "cancelled"})


@dataclass(frozen=True)
class _Owner:
    kind: str
    item_id: int
    task_num: int | None = None


@dataclass(frozen=True)
class _Worktree:
    path: Path
    branch: str


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _row_value(row: Any, key: str, index: int) -> Any:
    return row[key] if hasattr(row, "keys") else row[index]


def _terminal_owner(
    conn: Any,
    *,
    branch: str,
    path: Path | None,
) -> _Owner | None:
    """Return the unique terminal DB owner, never infer one from a name."""
    marker = _p(conn)
    owners: set[_Owner] = set()
    try:
        rows = conn.execute(
            f"SELECT id, status FROM items WHERE worktree = {marker}",
            (branch,),
        ).fetchall()
        for row in rows:
            if str(_row_value(row, "status", 1)) not in _ITEM_TERMINAL:
                return None
            owners.add(_Owner("item", int(_row_value(row, "id", 0))))

        rows = conn.execute(
            "SELECT epic_id, task_num, status FROM epic_tasks "
            f"WHERE worktree = {marker}",
            (branch,),
        ).fetchall()
        for row in rows:
            if str(_row_value(row, "status", 2)) not in TASK_TERMINAL_SUCCESS:
                return None
            owners.add(
                _Owner(
                    "epic_task",
                    int(_row_value(row, "epic_id", 0)),
                    int(_row_value(row, "task_num", 1)),
                )
            )

        if path is not None:
            rows = conn.execute(
                "SELECT edc.epic_id, i.status FROM epic_dispatch_chains edc "
                "JOIN items i ON i.id = edc.epic_id "
                f"WHERE edc.worktree = {marker} OR edc.worktree_path = {marker}",
                (branch, str(path)),
            ).fetchall()
            for row in rows:
                if str(_row_value(row, "status", 1)) not in _ITEM_TERMINAL:
                    return None
                owners.add(
                    _Owner("item", int(_row_value(row, "epic_id", 0)))
                )
    except Exception:  # noqa: BLE001 - missing/stale DB shape means preserve
        return None
    return next(iter(owners)) if len(owners) == 1 else None


def _has_active_authority(
    conn: Any,
    owner: _Owner,
    path: Path | None,
) -> bool:
    """Conservatively treat lookup failure as active authority."""
    marker = _p(conn)
    try:
        if owner.kind == "item":
            row = conn.execute(
                "SELECT 1 FROM work_claims WHERE released_at IS NULL "
                f"AND target_kind = 'item' AND item_id = {marker} LIMIT 1",
                (owner.item_id,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT 1 FROM work_claims WHERE released_at IS NULL "
                "AND target_kind = 'epic_task' "
                f"AND epic_id = {marker} AND task_num = {marker} LIMIT 1",
                (owner.item_id, owner.task_num),
            ).fetchone()
        if row is not None:
            return True
        row = conn.execute(
            "SELECT 1 FROM path_claims "
            "WHERE state IN ('planned', 'blocked', 'active') AND ("
            f"(owner_kind = 'item' AND owner_item_id = {marker}) OR "
            f"(owner_kind IS NULL AND item_id = {marker})"
            ") LIMIT 1",
            (owner.item_id, owner.item_id),
        ).fetchone()
        if row is not None:
            return True
        if path is not None:
            row = conn.execute(
                "SELECT 1 FROM harness_sessions WHERE ended_at IS NULL "
                f"AND workspace = {marker} LIMIT 1",
                (str(path),),
            ).fetchone()
            if row is not None:
                return True
    except Exception:  # noqa: BLE001 - fail closed
        return True
    return False


def item_cleanup_authority_blocks_prune(conn: Any, item_id: int) -> bool:
    """Return true when item authority is active or cannot be proven idle."""
    return _has_active_authority(conn, _Owner("item", int(item_id)), None)


def _worktrees(run_git: Callable[..., Any], repo_root: str) -> list[_Worktree] | None:
    result = run_git(
        ["worktree", "list", "--porcelain"], cwd=repo_root, capture=True
    )
    if result.returncode != 0:
        return None
    entries: list[_Worktree] = []
    path: Path | None = None
    for line in [*result.stdout.splitlines(), ""]:
        if line.startswith("worktree "):
            path = Path(line.removeprefix("worktree ")).resolve()
        elif line.startswith("branch refs/heads/") and path is not None:
            entries.append(
                _Worktree(path, line.removeprefix("branch refs/heads/"))
            )
            path = None
        elif not line:
            path = None
    return entries


def _is_managed_path(path: Path, repo_root: Path) -> bool:
    roots = (repo_root / ".worktrees", repo_root / ".claude" / "worktrees")
    return any(path != root and path.is_relative_to(root) for root in roots)


def _clean(run_git: Callable[..., Any], worktree: _Worktree) -> bool:
    from yoke_core.engines.merge_worktree_cleanliness import (
        clean_after_disposable_cache_removal,
    )

    return clean_after_disposable_cache_removal(run_git, worktree.path)


def _merged(
    run_git: Callable[..., Any],
    repo_root: str,
    branch: str,
    base: str,
) -> bool:
    result = run_git(
        ["merge-base", "--is-ancestor", branch, base],
        cwd=repo_root,
        capture=True,
    )
    return result.returncode == 0


def prune_managed_worktrees(
    *,
    parent: Any,
    repo_root: str,
    target: str,
) -> None:
    """Remove only clean, unclaimed, terminal work already merged to target."""
    run_git = parent._run_git
    emit = parent._print
    root = Path(repo_root).resolve()
    base = f"origin/{target}"
    fetched = run_git(["fetch", "origin", target], cwd=repo_root, capture=True)
    if fetched.returncode != 0:
        emit(f"Skipping automatic worktree pruning: could not refresh {base}")
        return
    entries = _worktrees(run_git, repo_root)
    if entries is None:
        emit("Skipping automatic worktree pruning: worktree registry unavailable")
        return
    try:
        conn = parent._connect()
    except Exception as exc:  # noqa: BLE001 - fail closed
        emit(
            "Skipping automatic worktree pruning: DB authority unavailable "
            f"({exc.__class__.__name__})"
        )
        return

    checked_out = {entry.branch for entry in entries}
    try:
        for entry in entries:
            if not _is_managed_path(entry.path, root):
                continue
            owner = _terminal_owner(
                conn, branch=entry.branch, path=entry.path
            )
            if owner is None:
                continue
            if _has_active_authority(conn, owner, entry.path):
                emit(f"Preserving actively claimed worktree: {entry.path}")
                continue
            if not _clean(run_git, entry):
                emit(f"Preserving dirty or unverifiable worktree: {entry.path}")
                continue
            if not _merged(run_git, repo_root, entry.branch, base):
                emit(f"Preserving unmerged worktree branch: {entry.branch}")
                continue
            removed = run_git(
                ["worktree", "remove", str(entry.path)],
                cwd=repo_root,
                capture=True,
            )
            if removed.returncode != 0:
                emit(f"Preserving worktree after removal refusal: {entry.path}")
                continue
            emit(f"Pruned terminal merged worktree: {entry.path}")
            checked_out.discard(entry.branch)
            deleted = run_git(
                ["branch", "-d", entry.branch], cwd=repo_root, capture=True
            )
            if deleted.returncode != 0:
                emit(f"Preserved local branch after delete refusal: {entry.branch}")

        branches = run_git(
            ["for-each-ref", "--format=%(refname:short)", "refs/heads"],
            cwd=repo_root,
            capture=True,
        )
        if branches.returncode != 0:
            return
        for branch in branches.stdout.splitlines():
            if branch in checked_out or branch == target:
                continue
            owner = _terminal_owner(conn, branch=branch, path=None)
            if owner is None or _has_active_authority(conn, owner, None):
                continue
            if not _merged(run_git, repo_root, branch, base):
                continue
            deleted = run_git(["branch", "-d", branch], cwd=repo_root, capture=True)
            if deleted.returncode == 0:
                emit(f"Pruned terminal merged local branch: {branch}")
    finally:
        conn.close()


__all__ = [
    "item_cleanup_authority_blocks_prune",
    "prune_managed_worktrees",
]
