"""Fail-closed pruning for DB-owned merged worktrees and branches."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.lifecycle_status import TASK_TERMINAL_SUCCESS
from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
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
        where = f"iw.branch = {marker}"
        params: tuple[Any, ...] = (branch,)
        if path is not None:
            where += f" OR iw.path = {marker}"
            params = (branch, str(path))
        rows = conn.execute(
            "SELECT iw.id AS lane_id, iw.item_id, i.status "
            "FROM item_worktrees iw JOIN items i ON i.id = iw.item_id "
            f"WHERE {where}",
            params,
        ).fetchall()
        for row in rows:
            lane_id = int(_row_value(row, "lane_id", 0))
            item_id = int(_row_value(row, "item_id", 1))
            task_rows = conn.execute(
                "SELECT epic_id, task_num, status FROM epic_tasks "
                f"WHERE item_worktree_id = {marker}",
                (lane_id,),
            ).fetchall()
            if not task_rows:
                if str(_row_value(row, "status", 2)) not in _ITEM_TERMINAL:
                    return None
                owners.add(_Owner("item", item_id))
                continue
            for task_row in task_rows:
                if (
                    str(_row_value(task_row, "status", 2))
                    not in TASK_TERMINAL_SUCCESS
                ):
                    return None
                owners.add(
                    _Owner(
                        "epic_task",
                        int(_row_value(task_row, "epic_id", 0)),
                        int(_row_value(task_row, "task_num", 1)),
                    )
                )
        if not rows:
            return None
        if any(owner.item_id not in {
            int(_row_value(row, "item_id", 1)) for row in rows
        } for owner in owners):
            # A task link whose parent disagrees with the universal lane owner
            # is corrupt; pruning must preserve it for diagnosis.
            return None
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
            "WHERE state IN ('planned', 'blocked', 'active') "
            f"AND owner_kind = 'item' AND owner_item_id = {marker} "
            "LIMIT 1",
            (owner.item_id,),
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


def _prune_verdict(
    branch: str, path: Path | None, state: dict[str, bool]
) -> dict[str, Any] | None:
    """Relay the fail-closed authority verdict for one branch / worktree.

    Returns the verdict dict, or ``None`` when DB authority is unreachable
    over the active transport (flagged on *state* so the caller can skip
    all pruning exactly as the old bare-connect failure did). The terminal
    owner + active authority reads run server-side over the relay; the
    prune/keep decision and every git deletion stay client-side.
    """
    try:
        resp = call_dispatcher(
            function_id="merge.prune.authority_verdict",
            target=TargetRef(kind="global"),
            payload={"branch": branch, "path": (str(path) if path else None)},
        )
    except Exception:  # noqa: BLE001 - transport failure == authority unavailable
        state["unavailable"] = True
        return None
    if not resp.success:
        state["unavailable"] = True
        return None
    return resp.result or {}


def _delete_remote_before_local(
    *,
    run_git: Callable[..., Any],
    emit: Callable[..., Any],
    repo_root: str,
    branch: str,
    target: str,
) -> bool:
    """Prove and delete ``origin/<branch>`` before discarding local refs."""
    from yoke_core.engines.remote_branch_cleanup import delete_remote_branch_if_merged

    result = delete_remote_branch_if_merged(
        run_git=lambda command: run_git(command, cwd=repo_root, capture=True),
        branch=branch,
        target_branch=target,
    )
    if result.status == "deleted":
        emit(f"Deleted merged remote branch: origin/{branch}")
    elif result.status == "preserved":
        emit(f"Preserving remote branch origin/{branch}: {result.reason}")
    return result.cleanup_complete


def prune_managed_worktrees(
    *,
    parent: Any,
    repo_root: str,
    target: str,
) -> None:
    """Prune clean, unclaimed, terminal lanes after remote-first delete.

    Authority verdicts relay via ``merge.prune.authority_verdict``; git stays
    local. Unreachable DB authority skips pruning. Incomplete remote cleanup
    preserves the local retry lane.
    """
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

    state = {"unavailable": False}
    checked_out = {entry.branch for entry in entries}
    for entry in entries:
        if not _is_managed_path(entry.path, root):
            continue
        verdict = _prune_verdict(entry.branch, entry.path, state)
        if state["unavailable"]:
            emit("Skipping automatic worktree pruning: DB authority unavailable")
            return
        assert verdict is not None  # not unavailable -> a dict
        if not verdict.get("prunable"):
            if verdict.get("reason") == "active_authority":
                emit(f"Preserving actively claimed worktree: {entry.path}")
            continue
        if not _clean(run_git, entry):
            emit(f"Preserving dirty or unverifiable worktree: {entry.path}")
            continue
        if not _merged(run_git, repo_root, entry.branch, base):
            emit(f"Preserving unmerged worktree branch: {entry.branch}")
            continue
        if not _delete_remote_before_local(
            run_git=run_git, emit=emit, repo_root=repo_root,
            branch=entry.branch, target=target,
        ):
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
        verdict = _prune_verdict(branch, None, state)
        if state["unavailable"]:
            emit("Skipping automatic worktree pruning: DB authority unavailable")
            return
        assert verdict is not None  # not unavailable -> a dict
        if not verdict.get("prunable"):
            continue
        if not _merged(run_git, repo_root, branch, base):
            continue
        if not _delete_remote_before_local(
            run_git=run_git, emit=emit, repo_root=repo_root,
            branch=branch, target=target,
        ):
            continue
        deleted = run_git(["branch", "-d", branch], cwd=repo_root, capture=True)
        if deleted.returncode == 0:
            emit(f"Pruned terminal merged local branch: {branch}")


__all__ = [
    "item_cleanup_authority_blocks_prune",
    "prune_managed_worktrees",
]
