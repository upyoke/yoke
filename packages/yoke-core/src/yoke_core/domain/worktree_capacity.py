"""What a checkout's worktree cap counts, and what frees it.

``max_active_worktrees`` counts the managed worktrees doing work: unmerged
item lanes and deploy-run driver trees. An item lane whose branch already
landed is only its worker's directory until release close-out retires it, so
it holds no slot. When a new lane would exceed the cap, lane creation first
runs the merged-lane sweep — the one cleanup boundary that always runs on the
lanes' own machine — and then refuses for what remains, naming each kind of
slot with the recovery that frees it.
"""

from __future__ import annotations

import sys
from typing import Any, List, Sequence

from yoke_core.engines.branch_landed_evidence import assess_branch_landed
from yoke_core.engines.deploy_run_worktree_naming import DRIVER_WORKTREE_PREFIX
from yoke_core.engines.deploy_run_worktree_retirement import (
    assess_deploy_run_worktrees,
)
from yoke_core.engines.git_worktree_registry import registered_worktrees

# The resolvable invocation, not the shorthand: a reader copies this out of a
# refusal, so `yoke doctor --fix` — which routes nowhere — would strand them.
DOCTOR_RETIRE_RECIPE = "yoke watch doctor -- --only HC-worktree-health --fix"


def _git(args: List[str], *, cwd: str, capture: bool = True) -> Any:
    from yoke_core.engines._merge_worktree_runtime import _run_git

    return _run_git(args, cwd=cwd, capture=capture)


def _carries_own_work(run_git: Any, branch: str) -> bool:
    """Whether ``branch`` moved past the commit it was created at.

    A lane that has not committed yet is also carried by its base, but it is
    starting work, not finished with it. The branch reflog's oldest entry is
    where the lane started; an unreadable reflog counts the lane.
    """
    reflog = run_git(["reflog", "show", "--format=%H", f"refs/heads/{branch}"])
    shas = (reflog.stdout or "").split() if reflog.returncode == 0 else []
    return len(shas) > 1 and shas[0] != shas[-1]


def landed_item_lanes(
    repo_root: str, active_names: Sequence[str], landed_base: str
) -> set[str]:
    """The item lanes that committed work ``landed_base`` already carries.

    Such a lane holds no capacity slot. A lane whose branch git cannot name,
    or that has not committed yet, counts; deploy-run driver trees are never
    item lanes.
    """
    item_lanes = [
        name for name in active_names if not name.startswith(DRIVER_WORKTREE_PREFIX)
    ]
    if not landed_base or not item_lanes:
        return set()
    branches = {
        entry.path.name: entry.branch
        for entry in registered_worktrees(_git, repo_root) or ()
    }

    def run_git(command: List[str]) -> Any:
        return _git(command, cwd=repo_root)

    landed: set[str] = set()
    for name in item_lanes:
        branch = branches.get(name)
        if (
            branch
            and assess_branch_landed(run_git, branch=branch, base=landed_base).landed
            and _carries_own_work(run_git, branch)
        ):
            landed.add(name)
    return landed


def capacity_recovery(
    repo_root: str, active_names: Sequence[str], landed: set[str]
) -> str:
    """Name what holds the counted slots and the recovery that frees each.

    Unmerged item lanes merge; finished runs' driver trees are retired by the
    doctor; an open run's driver tree is in use — its driver runs from it — and
    is never offered for retirement. ``landed`` lanes hold no slot.
    """
    unmerged = [
        name
        for name in active_names
        if not name.startswith(DRIVER_WORKTREE_PREFIX) and name not in landed
    ]
    driver_lanes = [
        name for name in active_names if name.startswith(DRIVER_WORKTREE_PREFIX)
    ]
    open_runs = (
        {
            lane.path.name
            for lane in assess_deploy_run_worktrees(repo_root=repo_root)
            if lane.run_is_open
        }
        if driver_lanes
        else set()
    )
    in_use = [name for name in driver_lanes if name in open_runs]
    finished = [name for name in driver_lanes if name not in open_runs]
    parts: List[str] = []
    if unmerged:
        parts.append(
            "Merge existing worktrees before creating more. "
            f"Item lanes: {', '.join(unmerged)}."
        )
    if finished:
        parts.append(
            f"{len(finished)} slot(s) are held by deploy-run driver trees, "
            f"which no merge retires — run `{DOCTOR_RETIRE_RECIPE}` to retire "
            f"the finished ones. Deploy-run lanes: {', '.join(finished)}."
        )
    if in_use:
        parts.append(
            f"{len(in_use)} slot(s) are in use by open deploy runs' drivers and "
            f"free when those runs finish. In-use deploy-run lanes: "
            f"{', '.join(in_use)}."
        )
    return " ".join(parts) if parts else "No counted worktrees were reported."


def landed_lanes_note(
    run_git: Any, repo_root: str, lanes: Sequence[tuple[str, str, str]]
) -> str:
    """Name the ``(name, branch, target)`` lanes whose work landed on target.

    A target is read as ``origin/<target>`` when the checkout has a remote,
    as the landed-lane proof reads it. One ``--merged`` ref read per target
    answers every lane, so a machine holding many lanes stays inside the
    doctor's budget. Those lanes await release close-out and hold no
    ``max_active_worktrees`` slot.
    """
    from yoke_core.engines.lane_cleanup_reads import LaneCleanupReads

    reads = LaneCleanupReads(run_git, repo_root, residues={}, worktrees={})
    prefix = "origin/" if lanes and reads.has_remote() else ""
    names = sorted(
        name
        for name, branch, target in lanes
        if reads.ancestor(branch, f"{prefix}{target}")
        and _carries_own_work(lambda command: run_git(command, cwd=repo_root), branch)
    )
    if not names:
        return ""
    return (
        f"- {len(names)} landed lane(s) await release close-out and are not "
        f"counted against max_active_worktrees: {', '.join(names)}"
    )


def retire_finished_lanes(repo_root: str, target: str) -> None:
    """Run the merged-lane sweep before a full checkout refuses a new lane.

    A member a deployment run closes has its lanes retired on the machine that
    settles the run, and a hosted control plane settles where no lane lives.
    Lane creation always runs on the lanes' own machine, so a full checkout
    first retires what the sweep proves finished — landed lanes of closed
    items and finished runs' driver trees — then refuses for what remains.
    The sweep names everything it removed or kept on stderr.
    """
    from yoke_core.engines.merge_worktree_safe_prune import prune_managed_worktrees

    def say(message: str, **_kw: Any) -> None:
        print(message, file=sys.stderr, flush=True)

    try:
        prune_managed_worktrees(repo_root=repo_root, target=target, emit=say)
    except Exception as exc:  # noqa: BLE001 - the capacity refusal follows
        say(
            f"Merged-lane sweep stopped before lane creation: {exc}. Run "
            f"`{DOCTOR_RETIRE_RECIPE}` to retire finished lanes."
        )


__all__ = [
    "DOCTOR_RETIRE_RECIPE",
    "capacity_recovery",
    "landed_item_lanes",
    "landed_lanes_note",
    "retire_finished_lanes",
]
