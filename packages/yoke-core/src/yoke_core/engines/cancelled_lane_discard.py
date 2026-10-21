"""Deleting every copy of a cancelled item's lane on this machine.

Cancelling an item is the operator's statement that its work is not wanted,
so its lanes are not held to the landing proof a finished item's lanes must
pass: the worktree goes even when it is dirty, locked or unmerged, then the
local branch, then the branch on ``origin``. What each lane held is read
first — the local and remote head commits and how many paths were
uncommitted — and written to the item's Progress Log, so the discarded
commits can still be named by SHA after the refs are gone.

Two boundaries reach this. The cancel itself deletes the lanes on the machine
that ran it; the machine-wide sweep (``merge_worktree_safe_prune``) deletes
the copies on every other machine the next time it runs there. A step git
refuses is named on the returned lane rather than retried here.
"""

from __future__ import annotations

import platform
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from yoke_contracts.harness_lane_cleanup import worktree_cleanup_warning
from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
from yoke_core.domain.public_item_target import public_item_target
from yoke_core.engines.git_worktree_registry import (
    first_output_line,
    is_managed_worktree_path,
    registered_worktrees,
)

CANCELLED_STATUS = "cancelled"
RECORD_FUNCTION_ID = "item_worktrees.cancelled_lanes.record"


@dataclass(frozen=True)
class DiscardedLane:
    """One cancelled lane: what it held, and anything git refused to delete."""

    branch: str
    worktree_path: str = ""
    head_sha: str = ""
    remote_head_sha: str = ""
    uncommitted_paths: int = 0
    kept: tuple[str, ...] = ()


def _runtime_git() -> Callable[..., Any]:
    from yoke_core.engines._merge_worktree_runtime import _run_git

    return _run_git


def _runtime_emit() -> Callable[..., Any]:
    from yoke_core.engines._merge_worktree_runtime import _print

    return _print


def _lane_worktree(
    git: Callable[..., Any], repo_root: str, branch: str
) -> Optional[Path]:
    root = Path(repo_root).resolve()
    for entry in registered_worktrees(git, repo_root) or ():
        if entry.branch == branch and is_managed_worktree_path(entry.path, root):
            return entry.path
    return None


def _local_head(git: Callable[..., Any], repo_root: str, branch: str) -> str:
    resolved = git(
        ["rev-parse", "--verify", "--quiet", f"refs/heads/{branch}^{{commit}}"],
        cwd=repo_root,
        capture=True,
    )
    return (resolved.stdout or "").strip() if resolved.returncode == 0 else ""


def _remove_worktree(
    git: Callable[..., Any], say: Callable[..., Any], repo_root: str, path: Path
) -> tuple[int, str]:
    """Remove the lane directory; return its uncommitted count and any refusal."""
    status = git(["status", "--porcelain"], cwd=str(path), capture=True)
    uncommitted = len(status.stdout.splitlines()) if status.returncode == 0 else 0
    if warning := worktree_cleanup_warning(path):
        return uncommitted, warning
    # Twice forced: git otherwise refuses a dirty tree once and a locked one twice.
    removed = git(
        ["worktree", "remove", "--force", "--force", str(path)],
        cwd=repo_root,
        capture=True,
    )
    if removed.returncode != 0:
        return uncommitted, (
            f"worktree {path} kept: git refused removal ({first_output_line(removed)})"
        )
    say(f"Deleted cancelled worktree: {path}")
    parent = path.parent
    if "/.worktrees" in str(parent):
        try:
            if not list(parent.iterdir()):
                parent.rmdir()
        except OSError:
            pass
    return uncommitted, ""


def _delete_remote(
    git: Callable[..., Any], say: Callable[..., Any], repo_root: str, branch: str
) -> tuple[str, str]:
    """Delete ``origin/<branch>``; return its head and any refusal."""
    remotes = git(["remote"], cwd=repo_root, capture=True)
    if remotes.returncode != 0 or "origin" not in remotes.stdout.split():
        return "", ""
    exact_ref = f"refs/heads/{branch}"
    listed = git(
        ["ls-remote", "--heads", "origin", exact_ref], cwd=repo_root, capture=True
    )
    if listed.returncode != 0:
        return "", f"remote branch origin/{branch} kept: origin could not be read"
    heads = [
        fields[0]
        for fields in (line.split() for line in listed.stdout.splitlines())
        if len(fields) == 2 and fields[1] == exact_ref
    ]
    if not heads:
        return "", ""
    deleted = git(
        [
            "push",
            f"--force-with-lease={exact_ref}:{heads[0]}",
            "origin",
            f":{exact_ref}",
        ],
        cwd=repo_root,
        capture=True,
    )
    if deleted.returncode != 0:
        return heads[0], (
            f"remote branch origin/{branch} kept: delete refused "
            f"({first_output_line(deleted)})"
        )
    say(f"Deleted cancelled remote branch: origin/{branch}")
    return heads[0], ""


def discard_cancelled_lane(
    *,
    repo_root: str,
    branch: str,
    target: str,
    run_git: Optional[Callable[..., Any]] = None,
    emit: Optional[Callable[..., Any]] = None,
) -> DiscardedLane:
    """Delete one cancelled lane's worktree, local branch and remote branch."""
    git = run_git or _runtime_git()
    say = emit or _runtime_emit()
    if branch == target:
        return DiscardedLane(branch, kept=(f"branch {branch} is the target branch",))
    if git(
        ["check-ref-format", "--branch", branch], cwd=repo_root, capture=True
    ).returncode:
        return DiscardedLane(branch, kept=(f"{branch!r} is not a valid branch name",))
    head = _local_head(git, repo_root, branch)
    kept: list[str] = []
    worktree = _lane_worktree(git, repo_root, branch)
    uncommitted = 0
    if worktree is not None:
        uncommitted, refusal = _remove_worktree(git, say, repo_root, worktree)
        if refusal:
            kept.append(refusal)
    if head and not kept:
        deleted = git(["branch", "-D", branch], cwd=repo_root, capture=True)
        if deleted.returncode != 0:
            kept.append(
                f"local branch {branch} kept: delete refused "
                f"({first_output_line(deleted)})"
            )
        else:
            say(f"Deleted cancelled local branch: {branch}")
    remote_head, refusal = _delete_remote(git, say, repo_root, branch)
    if refusal:
        kept.append(refusal)
    return DiscardedLane(
        branch,
        str(worktree or ""),
        head,
        remote_head,
        uncommitted,
        tuple(kept),
    )


def record_discarded_lanes(public_ref: str, lanes: tuple[DiscardedLane, ...]) -> str:
    """Write the deletions to the item's Progress Log; return a warning on refusal.

    The warning repeats every SHA so the evidence still reaches the operator
    when the control plane cannot record it.
    """
    if not lanes:
        return ""
    try:
        response = call_dispatcher(
            function_id=RECORD_FUNCTION_ID,
            target=public_item_target(public_ref),
            payload={
                "lanes": [asdict(lane) for lane in lanes],
                "machine": platform.node(),
            },
        )
    except Exception as exc:  # noqa: BLE001 - the deletions already happened
        detail = str(exc)
    else:
        if response.success:
            return ""
        detail = response.error.message if response.error is not None else "refused"
    deleted = "; ".join(
        f"{lane.branch} head={lane.head_sha or '-'} origin={lane.remote_head_sha or '-'}"
        for lane in lanes
    )
    return (
        f"{public_ref}: cancelled-lane deletion not recorded in the Progress Log "
        f"({detail}). Deleted: {deleted}. This output is the only record of "
        f"these SHAs: keep it, and if the refusal names a serving floor, "
        f"upgrade the server to a release that serves {RECORD_FUNCTION_ID}."
    )


def discard_and_record(
    repo_root: str,
    branch: str,
    target: str,
    public_ref: str,
    *,
    run_git: Optional[Callable[..., Any]] = None,
    emit: Optional[Callable[..., Any]] = None,
) -> DiscardedLane:
    """Delete one cancelled lane and record it; the sweep's single entry point."""
    say = emit or _runtime_emit()
    lane = discard_cancelled_lane(
        repo_root=repo_root, branch=branch, target=target, run_git=run_git, emit=say
    )
    if warning := record_discarded_lanes(public_ref, (lane,)):
        say(f"WARNING: {warning}", err=True)
    return lane


__all__ = [
    "CANCELLED_STATUS",
    "DiscardedLane",
    "RECORD_FUNCTION_ID",
    "discard_and_record",
    "discard_cancelled_lane",
    "record_discarded_lanes",
]
