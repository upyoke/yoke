"""Bring an item lane current with its fetched base branch.

The full-CI gate updates a lane before publishing it, and
``yoke watch pytest --impacted`` updates it before every selection, so a
lane meets ``origin/<target>`` while the worker iterates instead of first at
the gate. Both callers share this one update.

A lane that already contains the fetched base is left alone. Otherwise
uncommitted work goes through the merge engine's safety-stash gate, so
nothing an update would disturb is unbacked; work the gate cannot classify
as Yoke-managed stops the update rather than riding it. Merge-shaped lanes
merge the base, which keeps prior conflict resolutions; linear lanes rebase.
A conflict aborts and names the conflicted paths, because resolving them is
the session's call. Every refusal is a :class:`LaneBaseUpdateRefused`
whose message starts with a named reason and ends with the recovery.
"""

from __future__ import annotations

import contextlib
import subprocess
import sys
from pathlib import Path

from yoke_contracts.git_hook_markers import HEAD_RECORDING_SKIP_ENV
from yoke_cli.config import credentialed_git
from yoke_core.domain import process_group_reaping


class LaneBaseUpdateRefused(Exception):
    """The lane could not be brought current; the message names why and the fix."""


def git(checkout: Path, *args: str, timeout: int = 120) -> subprocess.CompletedProcess:
    """Run one git command in its own reaping process group, credentialed.

    A rebase spawns helpers a plain kill leaves behind, so execution stays
    with the reaping runner; only the environment is delegated.
    """
    argv = ["-C", str(checkout), *args]
    skip = {HEAD_RECORDING_SKIP_ENV: "1"} if args[:1] == ("rebase",) else {}
    with credentialed_git.git_environment(argv, cwd=str(checkout)) as base:
        return process_group_reaping.run_in_process_group(
            ["git", *argv],
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**base, **skip},
        )


def merge_context(checkout: Path, *, branch: str, target: str, project: str):
    """The merge engine's context for a lane that is its own worktree."""
    from yoke_core.engines.merge_worktree_prepare import MergeArgs, MergeContext

    return MergeContext(
        args=MergeArgs(branch=branch, target=target),
        repo_root=str(checkout),
        worktree_path=str(checkout),
        project=project,
    )


def bring_lane_current(
    checkout: Path,
    *,
    branch: str,
    target: str,
    project: str,
) -> bool:
    """Make ``origin/<target>`` an ancestor of the lane's HEAD.

    Returns whether the lane moved. Raises :class:`LaneBaseUpdateRefused`
    with the lane untouched when it cannot.
    """
    fetched = git(
        checkout, "fetch", "--quiet", "--no-tags", "origin", target, timeout=300
    )
    if fetched.returncode != 0:
        detail = (fetched.stderr or fetched.stdout or "").strip()
        raise LaneBaseUpdateRefused(
            f"lane_base_fetch_failed: could not fetch origin/{target} before "
            f"updating {branch!r}: {detail or 'fetch failed'}. Restore access "
            "to origin and re-run."
        )
    contains_base = git(
        checkout, "merge-base", "--is-ancestor", f"origin/{target}", "HEAD"
    )
    if contains_base.returncode == 0:
        return False
    if contains_base.returncode != 1:
        detail = (contains_base.stderr or contains_base.stdout or "").strip()
        raise LaneBaseUpdateRefused(
            f"lane_base_compare_failed: could not compare {branch!r} with "
            f"origin/{target}: {detail or 'merge-base failed'}. Repair Git "
            "refs and re-run."
        )
    _require_clean_lane(checkout, branch=branch, target=target, project=project)
    _update(checkout, branch=branch, target=target)
    return True


def _require_clean_lane(
    checkout: Path, *, branch: str, target: str, project: str
) -> None:
    from yoke_core.engines.merge_worktree_prepare_state import (
        _stash_classify_gate,
    )

    ctx = merge_context(checkout, branch=branch, target=target, project=project)
    # The gate narrates to stdout, which a caller may own as a
    # machine-readable envelope; its narration belongs on stderr.
    with contextlib.redirect_stdout(sys.stderr):
        at_risk = _stash_classify_gate(ctx)
    if at_risk is not None:
        raise LaneBaseUpdateRefused(
            f"lane_uncommitted_work: lane {branch!r} is behind origin/{target} "
            "and carries uncommitted work that is not Yoke-managed; it is "
            f"backed up in stash 'yoke-pre-rebase-{branch}'. Commit it and "
            "re-run, so the lane can be updated without disturbing your work."
        )


def _update(checkout: Path, *, branch: str, target: str) -> None:
    """Merge the fetched base into merge-shaped lanes; rebase linear lanes."""
    base = f"origin/{target}"
    topology = git(checkout, "rev-list", "--merges", f"{base}..HEAD")
    if topology.returncode:
        raise LaneBaseUpdateRefused(
            f"lane_topology_unavailable: cannot inspect {branch!r}: "
            f"{topology.stderr or topology.stdout}. Repair Git refs and re-run."
        )
    merge_shaped = bool(topology.stdout.strip())
    operation = "merge" if merge_shaped else "rebase"
    args = ("merge", "--no-edit", base) if merge_shaped else ("rebase", base)
    try:
        updated = git(checkout, *args, timeout=600)
    except subprocess.TimeoutExpired as exc:
        aborted = git(checkout, operation, "--abort")
        if aborted.returncode == 0:
            recovery = f"The in-progress {operation} was aborted and the lane restored."
        else:
            detail = (aborted.stderr or aborted.stdout or "abort failed").strip()
            recovery = (
                f"Automatic cleanup failed ({detail}); run `git -C {checkout} "
                f"{operation} --abort` to restore the lane."
            )
        raise LaneBaseUpdateRefused(
            f"lane_update_timed_out: {operation} of {branch!r} onto {base} "
            f"timed out after {exc.timeout}s. {recovery} Re-run."
        ) from exc
    if updated.returncode == 0:
        return
    conflicts = git(checkout, "diff", "--name-only", "--diff-filter=U")
    paths = tuple(conflicts.stdout.splitlines())
    aborted = git(checkout, operation, "--abort")
    cleanup = (
        f" Cleanup failed; run git -C {checkout} {operation} --abort first."
        if aborted.returncode
        else ""
    )
    detail = (
        ", ".join(paths)
        if paths
        else ((updated.stderr or updated.stdout or "").strip() or f"{operation} failed")
    )
    if merge_shaped:
        raise LaneBaseUpdateRefused(
            f"lane_merge_conflict: lane is merge-shaped; merging {base} failed: {detail}.{cleanup} "
            f"Merge {base} on the lane (`git -C {checkout} merge --no-edit {base}`), "
            "resolve and commit, and re-run."
        )
    raise LaneBaseUpdateRefused(
        f"lane_rebase_conflict: rebasing {branch!r} onto {base} conflicts: {detail}.{cleanup} "
        f"Rebase on the lane (`git -C {checkout} rebase {base}`), resolve the "
        f"conflicts, run `git -C {checkout} rebase --continue`, and re-run."
    )


__all__ = [
    "LaneBaseUpdateRefused",
    "bring_lane_current",
    "git",
    "merge_context",
]
