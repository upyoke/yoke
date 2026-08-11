"""Retiring one item lane whose branch has landed on the target branch.

A lane is four things describing one piece of work — a worktree directory, a
local branch, a remote branch, and the control-plane row that records where
they live — so they retire together. Leaving any one behind strands the next
reader that resolves a lane by its recorded path, and leaving all of them
behind is what an operator eventually sweeps by hand.

Two merge boundaries reach this. The local engine removes the directory it
merged from inline, while it still holds the context, and calls in here only
for the row. A queue landing has no such inline step: the merge happens on
GitHub, and the process watching it holds the branch name and nothing else.
So it prunes the whole lane from here, proving the landing against a freshly
fetched ``origin/<target>`` first — which is the same proof the local engine
verifies its own merge with, and the only one that holds for a merge commit
this checkout never created.

Every step fails toward preserving. An unmerged branch, a dirty worktree, an
ambiguous remote, or a refused deletion leaves the lane in place with the
reason named, because a preserved lane costs an operator one sweep while a
wrongly deleted one costs the work.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional

from yoke_contracts.api.function_call import TargetRef
from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
from yoke_core.engines.merge_worktree_cleanliness import (
    clean_after_disposable_cache_removal,
)
from yoke_core.engines.merge_worktree_safe_prune import (
    is_managed_worktree_path,
    registered_worktrees,
)
from yoke_core.engines.remote_branch_cleanup import (
    delete_remote_branch_if_merged,
)


def _runtime_git() -> Callable[..., Any]:
    from yoke_core.engines._merge_worktree_runtime import _run_git

    return _run_git


def _runtime_emit() -> Callable[..., Any]:
    from yoke_core.engines._merge_worktree_runtime import _print

    return _print


def release_lane_row(
    item_id: Optional[int | str],
    branch: str,
    *,
    emit: Callable[..., Any],
) -> None:
    """Retire the lane row for a worktree that has been removed.

    The directory and the row describe one lane, so they retire together.
    Leaving the row ``active`` over a removed directory strands every reader
    that resolves a lane by its recorded path — including the verification
    tree-binding guard, whose refusal then blocks the very done-gate run that
    would have released the row.

    Advisory by construction: the merge has already landed and been verified
    against origin by the time this runs, so a control plane that cannot be
    reached degrades to a warning rather than unwinding a completed merge.
    """
    if not item_id:
        return
    try:
        response = call_dispatcher(
            function_id="item_worktrees.release_merged_lane",
            target=TargetRef(kind="item", item_id=int(item_id)),
            payload={"branch": branch},
        )
    except Exception as exc:  # noqa: BLE001 - advisory, never unwinds a merge
        emit(
            f"WARNING: lane row for {branch} left active after "
            f"worktree removal: {exc}",
            err=True,
        )
        return
    if not response.success:
        detail = (
            response.error.message
            if response.error is not None
            else "release refused"
        )
        emit(
            f"WARNING: lane row for {branch} left active after "
            f"worktree removal: {detail}",
            err=True,
        )


def _lane_worktree(
    run_git: Callable[..., Any], repo_root: str, branch: str
) -> Optional[Path]:
    """The managed worktree directory checked out on ``branch``, if any."""
    entries = registered_worktrees(run_git, repo_root)
    if entries is None:
        return None
    root = Path(repo_root).resolve()
    for entry in entries:
        if entry.branch == branch and is_managed_worktree_path(entry.path, root):
            return entry.path
    return None


def _remove_empty_parent(path: Path) -> None:
    parent = path.parent
    if "/.worktrees" not in str(parent):
        return
    try:
        if not list(parent.iterdir()):
            parent.rmdir()
    except OSError:
        pass


def prune_landed_lane(
    *,
    repo_root: str,
    branch: str,
    target: str,
    item_id: Optional[int | str] = None,
    run_git: Optional[Callable[..., Any]] = None,
    emit: Optional[Callable[..., Any]] = None,
) -> tuple[str, ...]:
    """Retire one landed lane; return the reasons anything was preserved.

    An empty result means the lane is gone: no remote branch, no worktree, no
    local branch, and a released row. Any other result names what survived and
    why, so the caller can surface it instead of reporting a clean landing over
    a lane that is still on disk.
    """
    git = run_git or _runtime_git()
    say = emit or _runtime_emit()
    base = f"origin/{target}"

    fetched = git(["fetch", "origin", target], cwd=repo_root, capture=True)
    if fetched.returncode != 0:
        return (f"lane {branch} preserved: could not refresh {base}",)
    landed = git(
        ["merge-base", "--is-ancestor", branch, base],
        cwd=repo_root,
        capture=True,
    )
    if landed.returncode != 0:
        return (f"lane {branch} preserved: branch is not merged into {base}",)

    remote = delete_remote_branch_if_merged(
        run_git=lambda command: git(command, cwd=repo_root, capture=True),
        branch=branch,
        target_branch=target,
    )
    if remote.status == "deleted":
        say(f"Deleted merged remote branch: origin/{branch}")
    if not remote.cleanup_complete:
        return (
            f"lane {branch} preserved so remote cleanup can be retried: "
            f"{remote.reason}",
        )

    worktree_path = _lane_worktree(git, repo_root, branch)
    if worktree_path is not None:
        if not clean_after_disposable_cache_removal(git, worktree_path):
            return (
                f"lane {branch} preserved: worktree {worktree_path} is dirty "
                "or unverifiable",
            )
        removed = git(
            ["worktree", "remove", str(worktree_path)],
            cwd=repo_root,
            capture=True,
        )
        if removed.returncode != 0:
            return (
                f"lane {branch} preserved: worktree removal refused for "
                f"{worktree_path}",
            )
        say(f"Pruned merged worktree: {worktree_path}")
        _remove_empty_parent(worktree_path)

    release_lane_row(item_id, branch, emit=say)

    # Forced, because the freshly fetched ancestry proof above is the stronger
    # one: ``git branch -d`` proves containment in whatever this checkout has
    # checked out, which lags origin after a merge this checkout never made.
    deleted = git(["branch", "-D", branch], cwd=repo_root, capture=True)
    if deleted.returncode != 0:
        return (f"local branch {branch} preserved after delete refusal",)
    say(f"Pruned merged local branch: {branch}")
    return ()


__all__ = ["prune_landed_lane", "release_lane_row"]
