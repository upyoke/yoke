"""Merge-state and recovery-evidence guards for done transition."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional


def _parent():
    from yoke_core.engines import done_transition as _dt

    return _dt


def _check_merge_guard(
    lane_branch: str,
    project_repo: Path,
    base_branch: str,
) -> bool:
    """Return whether the lane is already represented on the remote base."""
    if not lane_branch:
        return False
    verify = _parent()._run_git(
        ["-C", str(project_repo), "rev-parse", "--verify", lane_branch],
        capture=True,
    )
    if verify.returncode != 0:
        print(
            f"Merge guard: branch '{lane_branch}' not found locally "
            "(likely already merged and cleaned up) — skipping merge step."
        )
        return True

    _parent()._run_git(
        ["-C", str(project_repo), "fetch", "origin", base_branch],
        capture=True,
    )
    target_ref = f"origin/{base_branch}"
    origin_check = _parent()._run_git(
        ["-C", str(project_repo), "rev-parse", "--verify", target_ref],
        capture=True,
    )
    if origin_check.returncode != 0:
        target_ref = base_branch
    ancestry = _parent()._run_git(
        [
            "-C",
            str(project_repo),
            "merge-base",
            "--is-ancestor",
            lane_branch,
            target_ref,
        ],
        capture=True,
    )
    if ancestry.returncode == 0:
        print(
            f"Merge guard: branch '{lane_branch}' is merged to "
            f"{target_ref} — skipping merge step."
        )
        return True
    log_check = _parent()._run_git(
        [
            "-C",
            str(project_repo),
            "log",
            "--oneline",
            f"--grep={lane_branch}",
            target_ref,
        ],
        capture=True,
    )
    first_line = (
        (log_check.stdout or "").strip().split("\n")[0] if log_check.stdout else ""
    )
    if first_line:
        print(
            f"Merge guard: squash-merge detected for branch '{lane_branch}' "
            f"on {target_ref} — skipping merge step."
        )
        return True
    print(
        f"Merge guard: branch '{lane_branch}' not yet merged to "
        f"{target_ref} — Step 4 will merge."
    )
    return False


def _verify_recovery_evidence(
    item_id: int,
    project_repo: Path,
    base_branch: str,
) -> bool:
    """Return whether the remote base contains item-specific merge evidence."""
    _parent()._run_git(
        ["-C", str(project_repo), "fetch", "origin", base_branch],
        capture=True,
    )
    target_ref = f"origin/{base_branch}"
    origin_check = _parent()._run_git(
        ["-C", str(project_repo), "rev-parse", "--verify", target_ref],
        capture=True,
    )
    if origin_check.returncode != 0:
        target_ref = base_branch
    log_check = _parent()._run_git(
        [
            "-C",
            str(project_repo),
            "log",
            "--oneline",
            f"--grep=YOK-{item_id}",
            target_ref,
        ],
        capture=True,
    )
    return bool((log_check.stdout or "").strip())


def _handle_resume_from_step6(
    item_id: int,
    project_repo: Path,
    base_branch: str,
    old_status: str,
    result,
    result_file: str,
) -> Optional[int]:
    """Validate recovery evidence before resuming post-merge work."""
    if not _verify_recovery_evidence(item_id, project_repo, base_branch):
        print(
            f"\nError: YOK-{item_id} has no active worktree lane and no merge "
            f"evidence found on origin/{base_branch}.\n"
            "State is inconsistent — refusing to skip merge step.\n"
            "If the branch was merged out-of-band, push the merge commit "
            "to origin and retry. Otherwise recreate the item worktree lane "
            f"with `yoke worktree preflight YOK-{item_id}`.",
            file=sys.stderr,
        )
        print(f"RESULT_FILE={result_file}")
        return result.fail(result_file, 2, "2d-recovery-no-evidence")
    print(
        f"Pre-flight: merge already completed (no active lane), status is "
        f"'{old_status}'."
    )
    print("Resuming from step 6 (status update and post-merge steps).")
    return None
