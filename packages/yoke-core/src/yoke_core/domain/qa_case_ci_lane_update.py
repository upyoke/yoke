"""Update an unexamined CI lane without flattening resolved merge ancestry."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable

from yoke_core.domain.qa_case_execution import QaCaseExecutionError


def update_lane(checkout: Path, *, branch: str, target: str, git: Callable) -> None:
    """Merge the fetched base into merge-shaped lanes; rebase linear lanes."""
    base = f"origin/{target}"
    topology = git(checkout, "rev-list", "--merges", f"{base}..HEAD")
    if topology.returncode:
        raise QaCaseExecutionError(
            f"lane_topology_unavailable: cannot inspect {branch!r}: "
            f"{topology.stderr or topology.stdout}. Repair Git refs and re-run the gate."
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
        raise QaCaseExecutionError(
            f"{operation} of {branch!r} onto {base} timed out after "
            f"{exc.timeout}s. {recovery} Re-run the gate."
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
        raise QaCaseExecutionError(
            f"lane_merge_conflict: lane is merge-shaped; merging {base} failed: {detail}.{cleanup} "
            f"Merge {base} on the lane (`git -C {checkout} merge --no-edit {base}`), "
            "resolve and commit, and re-run the gate."
        )
    raise QaCaseExecutionError(
        f"rebasing {branch!r} onto origin/{target} conflicts: {detail}.{cleanup} "
        f"Rebase on the lane (`git -C {checkout} rebase {base}`), resolve the "
        f"conflicts, run `git -C {checkout} rebase --continue`, and re-run the gate."
    )
