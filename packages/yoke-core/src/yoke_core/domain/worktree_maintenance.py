"""Landed-lane reporting and the sweep before new lane creation."""

from __future__ import annotations

import sys
from typing import Any, Sequence


def _carries_own_work(run_git: Any, branch: str) -> bool:
    """Whether ``branch`` moved past the commit it was created at.

    A lane that has not committed yet is also carried by its base, but it is
    starting work, not finished with it. The branch reflog's oldest entry is
    where the lane started; an unreadable reflog leaves its state unproven.
    """
    reflog = run_git(["reflog", "show", "--format=%H", f"refs/heads/{branch}"])
    shas = (reflog.stdout or "").split() if reflog.returncode == 0 else []
    return len(shas) > 1 and shas[0] != shas[-1]


def landed_lanes_note(
    run_git: Any, repo_root: str, lanes: Sequence[tuple[str, str, str]]
) -> str:
    """Name the ``(name, branch, target)`` lanes whose work landed on target.

    A target is read as ``origin/<target>`` when the checkout has a remote,
    as the landed-lane proof reads it. One ``--merged`` ref read per target
    answers every lane, so a machine holding many lanes stays inside the
    doctor's budget. Those lanes await release close-out.
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
    return f"- {len(names)} landed lane(s) await release close-out: {', '.join(names)}"


def retire_finished_lanes(repo_root: str, target: str) -> None:
    """Sweep finished lanes before creation, naming removals and holds on stderr."""
    from yoke_core.engines.merge_worktree_safe_prune import prune_managed_worktrees

    def say(message: str, **_kw: Any) -> None:
        print(message, file=sys.stderr, flush=True)

    try:
        prune_managed_worktrees(repo_root=repo_root, target=target, emit=say)
    except Exception as exc:  # noqa: BLE001 - cleanup does not block creation
        say(
            f"Merged-lane sweep stopped before lane creation: {exc}. The "
            "relay's next lane sweep retries it; check that the relay runs "
            "with `yoke relay status`."
        )
