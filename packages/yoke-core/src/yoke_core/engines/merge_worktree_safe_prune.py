"""Fail-closed sweep of merged, terminal, unclaimed lanes on this machine.

The per-lane retirement at landing (``merge_landed_lane_cleanup``) can refuse
— a dirty tree, a locked worktree, an incomplete remote delete — and a lane
whose item closes at release is never retired by its landing at all. The
standing relay runs this sweep over every checkout it maps, at start and
every 15 minutes, so those lanes retire on the machine that holds them; a
standalone close-out, a merge, and lane creation at the worktree cap run it
too. Each lane goes through ``prune_landed_lane``, the landing's own proof:
the control plane must name a terminal owner with no live authority
(``merge.prune.authority_verdict`` over the active transport), the tree must
hold nothing but named caches, ``origin/<target>`` must retain every change
the branch carries, and the remote branch goes before any local ref.
Unreachable authority, or another sweep holding the checkout's lock, skips
everything. What was removed and what was kept, each kept lane with its
reason, comes back as a :class:`WorktreeSweep`.

A lane whose owner is a cancelled item is the exception the verdict names:
cancelling discards the work, so ``cancelled_lane_discard`` deletes its
worktree and branches without the landing and residue proofs. This is how a
cancel reaches every machine other than the one that ran it.

The sweep also retires a self-deploy run's detached driver tree through
``deploy_run_worktree_retirement`` once the run is over, before the item
pass. A driver path has no item owner, so that pass leaves it alone.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from yoke_contracts.api.function_call import TargetRef
from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
from yoke_core.engines.cancelled_lane_discard import discard_and_record
from yoke_core.engines.deploy_run_worktree_retirement import (
    retire_terminal_deploy_run_worktrees,
)
from yoke_core.engines.git_worktree_registry import (
    is_managed_worktree_path,
    registered_worktrees,
)
from yoke_core.engines.lane_sweep_lock import SWEEP_LOCK_HELD, lane_sweep_lock
from yoke_core.engines.merge_landed_lane_cleanup import (
    prune_landed_lane,
    release_lane_row,
)
from yoke_core.engines.worktree_removal import finish_tombstones


@dataclass(frozen=True)
class PreservedLane:
    path: str
    reason: str


@dataclass(frozen=True)
class WorktreeSweep:
    """What one sweep removed and what it left on disk, each with a reason."""

    removed: tuple[str, ...] = ()
    preserved: tuple[PreservedLane, ...] = ()
    skipped: str = ""

    def payload(self) -> dict[str, Any]:
        return {
            "removed": list(self.removed),
            "preserved": [asdict(lane) for lane in self.preserved],
            "skipped": self.skipped,
        }


def _runtime_git() -> Callable[..., Any]:
    from yoke_core.engines._merge_worktree_runtime import _run_git

    return _run_git


def _runtime_emit() -> Callable[..., Any]:
    from yoke_core.engines._merge_worktree_runtime import _print

    return _print


def _prune_verdict(
    branch: str, path: Path | None, state: dict[str, bool]
) -> dict[str, Any] | None:
    """Relay the fail-closed authority verdict for one branch / worktree.

    Returns the verdict dict, or ``None`` when DB authority is unreachable
    over the active transport (flagged on *state* so the caller skips all
    pruning). The terminal owner + active authority reads run server-side;
    the prune/keep decision and every git deletion stay client-side.
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


_KEPT_VERDICTS = {
    "active_authority": "actively claimed",
    "no_terminal_owner": (
        "no single terminal owner: its item is still open, or it is shared"
    ),
}


def _skipped(
    emit: Callable[..., Any],
    reason: str,
    removed: tuple[str, ...] = (),
    preserved: tuple[PreservedLane, ...] = (),
) -> WorktreeSweep:
    emit(f"Skipping automatic worktree pruning: {reason}")
    return WorktreeSweep(removed, preserved, reason)


def prune_managed_worktrees(
    *,
    repo_root: str,
    target: str,
    run_git: Callable[..., Any] | None = None,
    emit: Callable[..., Any] | None = None,
) -> WorktreeSweep:
    """Prune clean, unclaimed, terminal lanes, one sweep per checkout at a time.

    No origin remote, unreachable DB authority or another sweep holding the
    checkout skips pruning. Every kept worktree is named with its reason.
    """
    git = run_git or _runtime_git()
    say = emit or _runtime_emit()
    if git(["remote", "get-url", "origin"], cwd=repo_root, capture=True).returncode:
        return _skipped(say, "no origin remote (local-only project)")
    common = git(["rev-parse", "--git-common-dir"], cwd=repo_root, capture=True)
    if common.returncode:
        return _skipped(say, "git common directory unreadable")
    with lane_sweep_lock(Path(repo_root, common.stdout.strip())) as held:
        if not held:
            return _skipped(say, SWEEP_LOCK_HELD)
        return _sweep(git, say, repo_root, target)


def _sweep(
    git: Callable[..., Any], say: Callable[..., Any], repo_root: str, target: str
) -> WorktreeSweep:
    root = Path(repo_root).resolve()
    if git(["fetch", "origin", target], cwd=repo_root, capture=True).returncode:
        return _skipped(say, f"could not refresh origin/{target}")
    entries = registered_worktrees(git, repo_root)
    if entries is None:
        return _skipped(say, "worktree registry unavailable")

    removed: list[str] = []
    preserved: list[PreservedLane] = []

    def keep(path: Path, reason: str) -> None:
        say(f"Preserving worktree {path}: {reason}")
        preserved.append(PreservedLane(str(path), reason))

    # Interrupted removals' tombstones and deploy-run driver trees retire
    # first: the item pass below can return early on unreachable authority.
    for leftover in finish_tombstones(repo_root):
        if leftover.reason:
            say(f"WARNING: {leftover.reason}", err=True)
    for lane in retire_terminal_deploy_run_worktrees(repo_root=repo_root):
        if lane.retired:
            say(f"Retired finished deploy-run worktree: {lane.path}")
            removed.append(str(lane.path))
        else:
            keep(lane.path, lane.reason)

    state = {"unavailable": False}
    checked_out = {entry.branch for entry in entries}
    for entry in entries:
        if not is_managed_worktree_path(entry.path, root):
            continue
        verdict = _prune_verdict(entry.branch, entry.path, state)
        if state["unavailable"]:
            return _skipped(say, "DB authority unavailable", tuple(removed), tuple(preserved))
        assert verdict is not None  # not unavailable -> a dict
        if not verdict.get("prunable"):
            reason = str(verdict.get("reason") or "")
            keep(entry.path, _KEPT_VERDICTS.get(reason, reason or "not prunable"))
            continue
        if cancelled_ref := verdict.get("cancelled_item_ref"):
            lane = discard_and_record(
                repo_root, entry.branch, target, cancelled_ref, run_git=git, emit=say
            )
            checked_out.discard(entry.branch)
            if lane.kept:
                keep(entry.path, "; ".join(lane.kept))
            else:
                removed.append(str(entry.path))
            continue
        if not (item_ref := verdict.get("item_ref")):
            keep(
                entry.path,
                "prune_owner_identity_unavailable: update the serving "
                "control plane to return item_ref, then retry the sweep",
            )
            continue
        if entry.lock_reason is not None:
            keep(
                entry.path,
                f"worktree is locked ({entry.lock_reason or 'no reason recorded'})",
            )
            continue
        absent, kept = not entry.path.is_dir(), ()
        try:
            if not absent:
                kept = _prune_lane(git, say, repo_root, entry.branch, target, item_ref)
        except FileNotFoundError:
            if entry.path.is_dir():
                raise
            absent = True
        if absent:
            # The branch pass below proves the branch on its own.
            say(f"Pruned registration for an absent worktree: {entry.path}")
            git(["worktree", "prune"], cwd=repo_root, capture=True)
            release_lane_row(item_ref, entry.branch, emit=say)
            removed.append(str(entry.path))
            checked_out.discard(entry.branch)
        elif entry.path.exists():
            # The path is already named; keep only why the lane survived.
            why = "; ".join(r.split(" preserved: ", 1)[-1] for r in kept)
            keep(entry.path, why or "worktree removal left it on disk")
        else:
            removed.append(str(entry.path))

    branches = git(
        ["for-each-ref", "--format=%(refname:short)", "refs/heads"],
        cwd=repo_root,
        capture=True,
    )
    if branches.returncode != 0:
        return WorktreeSweep(tuple(removed), tuple(preserved))
    for branch in branches.stdout.splitlines():
        if branch in checked_out or branch == target:
            continue
        verdict = _prune_verdict(branch, None, state)
        if state["unavailable"]:
            return _skipped(say, "DB authority unavailable", tuple(removed), tuple(preserved))
        assert verdict is not None  # not unavailable -> a dict
        if not verdict.get("prunable"):
            continue
        if cancelled_ref := verdict.get("cancelled_item_ref"):
            discard_and_record(
                repo_root, branch, target, cancelled_ref, run_git=git, emit=say
            )
            continue
        # No worktree here means no lane row to release: pass no item.
        for reason in _prune_lane(git, say, repo_root, branch, target, None):
            say(f"Preserving branch {branch}: {reason}")
    return WorktreeSweep(tuple(removed), tuple(preserved))


def _prune_lane(
    git: Callable[..., Any],
    say: Callable[..., Any],
    repo_root: str,
    branch: str,
    target: str,
    item_ref: Any,
) -> tuple[str, ...]:
    """Retire one lane through the per-lane proof the landing applies."""
    return prune_landed_lane(
        repo_root=repo_root,
        branch=branch,
        target=target,
        item_id=item_ref,
        run_git=git,
        emit=say,
        refresh_target=False,
    )


__all__ = [
    "PreservedLane",
    "WorktreeSweep",
    "prune_managed_worktrees",
]
