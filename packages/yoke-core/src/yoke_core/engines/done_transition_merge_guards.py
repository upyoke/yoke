"""Merge-state and recovery-evidence guards for done transition."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from yoke_contracts.public_ref import unresolved_item_ref
from yoke_core.domain.worktree_naming import legacy_worktree_name


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
    *,
    public_ref: Optional[str] = None,
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
    # A SEARCH KEY, never shown. Merge commits for a lane carry its branch
    # name, and lanes predating public-ref naming are recorded under the
    # legacy shape, so this is how their evidence is still found. It has to
    # stay item-specific: the unresolved display phrase would match any
    # commit that happens to quote it and accept another item's merge as
    # this item's evidence — and match nothing at all the rest of the time,
    # which is a guard that only ever fails open or useless.
    legacy_ref = legacy_worktree_name(item_id)
    search_refs = [ref for ref in (public_ref, legacy_ref) if ref]
    if len(search_refs) == 2 and search_refs[0] == search_refs[1]:
        search_refs.pop()
    for search_ref in search_refs:
        log_check = _parent()._run_git(
            [
                "-C",
                str(project_repo),
                "log",
                "--oneline",
                f"--grep={search_ref}",
                target_ref,
            ],
            capture=True,
        )
        if (log_check.stdout or "").strip():
            return True
    return False


def _handle_resume_from_step6(
    item_id: int,
    project_repo: Path,
    base_branch: str,
    old_status: str,
    result,
    result_file: str,
    *,
    public_ref: Optional[str] = None,
) -> Optional[int]:
    """Validate recovery evidence before resuming post-merge work."""
    if not _verify_recovery_evidence(
        item_id, project_repo, base_branch, public_ref=public_ref
    ):
        ref = public_ref or unresolved_item_ref()
        print(
            f"\nError: {ref} has no active worktree lane and no merge "
            f"evidence found on origin/{base_branch}.\n"
            "State is inconsistent — refusing to skip merge step.\n"
            "If the branch was merged out-of-band, push the merge commit "
            "to origin and retry. Otherwise recreate the item worktree lane "
            f"with `yoke worktree preflight {ref}`.",
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
