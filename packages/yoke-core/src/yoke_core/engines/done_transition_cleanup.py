"""Fail-closed cleanup for a completed item merge lane."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.backlog_session_attribution import _current_session_id


def _parent():
    from yoke_core.engines import done_transition as _dt

    return _dt


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _has_foreign_claim(item_id: int) -> bool:
    """Treat another owner or an unreadable claim registry as active."""
    caller = _current_session_id()
    try:
        with _parent()._connect() as conn:
            rows = conn.execute(
                "SELECT session_id FROM work_claims "
                "WHERE released_at IS NULL AND target_kind = 'item' "
                f"AND item_id = {_p(conn)}",
                (item_id,),
            ).fetchall()
    except Exception:  # noqa: BLE001 - cleanup must fail closed
        return True
    holders = {
        str(row["session_id"] if hasattr(row, "keys") else row[0])
        for row in rows
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


def _delete_remote_if_merged(
    project_repo: Path, branch: str, base_ref: str
) -> bool:
    """Delete an exact remote ref only after refreshed ancestry proof."""
    listed = _parent()._run_git(
        ["-C", str(project_repo), "ls-remote", "--heads", "origin", branch],
        capture=True,
    )
    if listed.returncode != 0:
        print(f"  Preserving remote branch: could not inspect origin/{branch}.")
        return False
    exact_ref = f"refs/heads/{branch}"
    advertised_refs = {
        fields[1]: fields[0]
        for line in (listed.stdout or "").splitlines()
        if len(fields := line.split("\t", 1)) == 2
    }
    if exact_ref not in advertised_refs:
        return True
    fetched = _parent()._run_git(
        [
            "-C",
            str(project_repo),
            "fetch",
            "origin",
            f"+refs/heads/{branch}:refs/remotes/origin/{branch}",
        ],
        capture=True,
    )
    remote_ref = f"origin/{branch}"
    if fetched.returncode != 0 or not _branch_merged(
        project_repo, remote_ref, base_ref
    ):
        print(f"  Preserving unmerged or unverifiable remote branch: {remote_ref}")
        return False
    resolved = _parent()._run_git(
        ["-C", str(project_repo), "rev-parse", remote_ref],
        capture=True,
    )
    expected_sha = (resolved.stdout or "").strip()
    if resolved.returncode != 0 or expected_sha != advertised_refs[exact_ref]:
        print(f"  Preserving remote branch after concurrent update: {remote_ref}")
        return False
    deleted = _parent()._run_git(
        [
            "-C",
            str(project_repo),
            "push",
            f"--force-with-lease={exact_ref}:{expected_sha}",
            "origin",
            f":{exact_ref}",
        ],
        capture=True,
    )
    if deleted.returncode != 0:
        print(f"  Preserving metadata after remote delete refusal: {remote_ref}")
        return False
    print(f"  Deleted merged remote branch: {remote_ref}")
    return True


def _cleanup_stale_branches(
    item_id: int,
    worktree_field: str,
    project_repo: Path,
    base_branch: str = "main",
) -> bool:
    """Remove only the current clean, registered, fully merged lane.

    Returns whether item worktree metadata can safely be cleared.  Any
    ambiguity leaves the filesystem, refs, and metadata intact so the
    terminal-item pruner can retry after ownership or dirtiness is resolved.
    """
    print("\n=== Step 4a: Safe worktree/branch cleanup ===")
    if _has_foreign_claim(item_id):
        print("  Preserving merge lane: another or unknown claim is active.")
        return False

    if worktree_field:
        valid_branch = _parent()._run_git(
            [
                "-C",
                str(project_repo),
                "check-ref-format",
                "--branch",
                worktree_field,
            ],
            capture=True,
        )
        if valid_branch.returncode != 0:
            print(
                "  Preserving merge lane: worktree metadata is not a valid "
                f"branch name ({worktree_field!r})."
            )
            return False

    refreshed = _parent()._run_git(
        ["-C", str(project_repo), "fetch", "origin", base_branch],
        capture=True,
    )
    if refreshed.returncode != 0:
        print(f"  Preserving merge lane: could not refresh origin/{base_branch}.")
        return False

    canonical = f"YOK-{item_id}"
    expected = {canonical}
    if worktree_field:
        expected.add(worktree_field)
    base_ref = f"origin/{base_branch}"
    wt_dir = project_repo / ".worktrees" / canonical

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

    for branch in sorted(expected):
        if not _delete_remote_if_merged(project_repo, branch, base_ref):
            return False

    if worktree_field.startswith("trial/") and not _cleanup_trial_branches(
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
