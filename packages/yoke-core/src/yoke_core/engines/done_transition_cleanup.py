"""Fail-closed cleanup for a completed item merge lane."""

from __future__ import annotations

import re
import sys
from pathlib import Path

from yoke_contracts.api.function_call import TargetRef
from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
from yoke_core.domain.backlog_session_attribution import _current_session_id
from yoke_core.engines.remote_branch_cleanup import delete_remote_branch_if_merged


def _parent():
    from yoke_core.engines import done_transition as _dt

    return _dt


def _has_foreign_claim(item_id: int) -> bool:
    """Treat another owner or an unreadable claim registry as active.

    Relays ``claims.work.holder_list`` (its item filter is the exact active
    item-claim query this gate used) so the read runs over an https control
    plane as well as a local Postgres connection. Cleanup must fail closed:
    a refused relay or a transport error reads as "a claim is active" (True),
    preserving the bare-connect ``except: return True`` behavior so a git
    prune never proceeds on an unreadable claim registry.
    """
    caller = _current_session_id()
    try:
        resp = call_dispatcher(
            function_id="claims.work.holder_list",
            target=TargetRef(kind="item", item_id=int(item_id)),
            payload={"item_id": int(item_id)},
        )
    except Exception:  # noqa: BLE001 - cleanup must fail closed
        return True
    if not resp.success:
        return True
    holders = {
        str(holder.get("session_id") or "")
        for holder in (resp.result or {}).get("holders", [])
    }
    return bool(holders and (not caller or holders != {caller}))


def _registered_branch(project_repo: Path, worktree_path: Path) -> str | None:
    listed = _parent()._run_git(
        ["-C", str(project_repo), "worktree", "list", "--porcelain"],
        capture=True,
    )
    if listed.returncode != 0:
        return None
    wanted = worktree_path.resolve()
    current_path: Path | None = None
    for line in [*(listed.stdout or "").splitlines(), ""]:
        if line.startswith("worktree "):
            current_path = Path(line.removeprefix("worktree ")).resolve()
        elif line.startswith("branch refs/heads/") and current_path == wanted:
            return line.removeprefix("branch refs/heads/")
        elif not line:
            current_path = None
    return None


def _branch_exists(project_repo: Path, branch: str) -> bool:
    result = _parent()._run_git(
        ["-C", str(project_repo), "rev-parse", "--verify", branch],
        capture=True,
    )
    return result.returncode == 0


def _branch_merged(project_repo: Path, branch: str, base_ref: str) -> bool:
    result = _parent()._run_git(
        [
            "-C",
            str(project_repo),
            "merge-base",
            "--is-ancestor",
            branch,
            base_ref,
        ],
        capture=True,
    )
    return result.returncode == 0


def _delete_remote_for_lane(
    project_repo: Path, branch: str, base_branch: str
) -> bool:
    """Prove and delete one remote via the shared leased helper."""
    result = delete_remote_branch_if_merged(
        run_git=lambda command: _parent()._run_git(
            ["-C", str(project_repo), *command],
            capture=True,
        ),
        branch=branch,
        target_branch=base_branch,
    )
    if result.status == "deleted":
        print(f"  Deleted merged remote branch: origin/{branch}")
    elif result.status == "preserved":
        print(f"  Preserving remote branch origin/{branch}: {result.reason}")
    return result.cleanup_complete


def _cleanup_stale_branches(
    item_id: int,
    lane_branch: str,
    project_repo: Path,
    base_branch: str = "main",
) -> bool:
    """Remove only the current clean, registered, fully merged lane.

    Returns whether the active lane can safely be released after the item
    reaches done. Remote delete runs first via the shared helper; any
    incomplete remote cleanup leaves the filesystem, refs, and lane intact so
    the terminal-item pruner can retry after ownership or dirtiness is
    resolved. Local ``git branch -d`` proves ancestry against
    ``origin/<base>`` (already refreshed), not upstream tracking.
    """
    print("\n=== Step 4a: Safe worktree/branch cleanup ===")
    if _has_foreign_claim(item_id):
        print("  Preserving merge lane: another or unknown claim is active.")
        return False

    if lane_branch:
        valid_branch = _parent()._run_git(
            [
                "-C",
                str(project_repo),
                "check-ref-format",
                "--branch",
                lane_branch,
            ],
            capture=True,
        )
        if valid_branch.returncode != 0:
            print(
                "  Preserving merge lane: the recorded branch is not valid "
                f"({lane_branch!r})."
            )
            return False

    refreshed = _parent()._run_git(
        ["-C", str(project_repo), "fetch", "origin", base_branch],
        capture=True,
    )
    if refreshed.returncode != 0:
        print(f"  Preserving merge lane: could not refresh origin/{base_branch}.")
        return False

    # The lane lives at .worktrees/<branch>; use the recorded branch
    # (public ref or legacy name) rather than reconstructing YOK-{internal_id}.
    from yoke_core.domain.worktree_naming import worktree_name_for_item

    canonical = lane_branch or worktree_name_for_item(None, item_id)
    expected = {canonical}
    if lane_branch:
        expected.add(lane_branch)
    base_ref = f"origin/{base_branch}"
    wt_dir = project_repo / ".worktrees" / canonical

    for branch in sorted(expected):
        if not _delete_remote_for_lane(project_repo, branch, base_branch):
            return False

    if wt_dir.exists():
        registered = _registered_branch(project_repo, wt_dir)
        if registered not in expected:
            print(f"  Preserving unregistered or mismatched worktree: {wt_dir}")
            return False
        from yoke_core.engines.merge_worktree_cleanliness import (
            clean_after_disposable_cache_removal,
        )

        if not clean_after_disposable_cache_removal(
            _parent()._run_git, wt_dir
        ):
            print(f"  Preserving dirty or unverifiable worktree: {wt_dir}")
            return False
        if not _branch_merged(project_repo, registered, base_ref):
            print(f"  Preserving unmerged worktree branch: {registered}")
            return False
        removed = _parent()._run_git(
            ["-C", str(project_repo), "worktree", "remove", str(wt_dir)],
            capture=True,
        )
        if removed.returncode != 0:
            print(f"  Preserving worktree after removal refusal: {wt_dir}")
            return False
        print(f"  Removed clean merged worktree: {wt_dir}")

    for branch in sorted(expected):
        if not _branch_exists(project_repo, branch):
            continue
        if not _branch_merged(project_repo, branch, base_ref):
            print(f"  Preserving unmerged local branch: {branch}")
            return False
        deleted = _parent()._run_git(
            ["-C", str(project_repo), "branch", "-d", branch],
            capture=True,
        )
        if deleted.returncode != 0:
            print(f"  Preserving local branch after delete refusal: {branch}")
            return False
        print(f"  Deleted merged local branch: {branch}")

    if lane_branch.startswith("trial/") and not _cleanup_trial_branches(
        project_repo, item_id=item_id
    ):
        return False
    print("Safe cleanup complete.")
    return True


def _cleanup_trial_branches(
    project_repo: Path, item_id: int | None = None
) -> bool:
    """Delete only trial refs whose tips are already retained by ``HEAD``."""
    pattern = f"trial/YOK-{item_id}" if item_id is not None else "trial/*"
    branches = _parent()._run_git(
        ["-C", str(project_repo), "branch", "--list", pattern],
        capture=True,
    )
    complete = branches.returncode == 0
    for line in (branches.stdout or "").splitlines():
        ref = line.strip().lstrip("* ")
        match = re.fullmatch(r"trial/YOK-(\d+)", ref)
        if not match:
            continue
        trial_item = int(match.group(1))
        if _parent()._query_item_field(trial_item, "status") != "done":
            complete = False
            continue
        if _has_foreign_claim(trial_item):
            complete = False
            continue
        if not _branch_merged(project_repo, ref, "HEAD"):
            print(f"  Preserving trial branch with unique commits: {ref}")
            complete = False
            continue
        deleted = _parent()._run_git(
            ["-C", str(project_repo), "branch", "-d", ref],
            capture=True,
        )
        if deleted.returncode != 0:
            complete = False
            print(
                f"  WARNING: Refused to delete trial branch {ref}",
                file=sys.stderr,
            )
    return complete


__all__ = ["_cleanup_stale_branches", "_cleanup_trial_branches"]
