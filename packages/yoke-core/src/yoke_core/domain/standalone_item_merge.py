"""The one merge boundary for an item branch that owns no epic lane.

Every standalone item branch — Dash, Blitz, and any Issue whose workflow
generates no task graph — lands on its project base branch through
:func:`merge_standalone_branch`. The function owns the merge itself and the
bookkeeping the merge produces (identity resolution, the ``merged_at`` stamp,
publishing the base branch, telemetry). Item bookkeeping that differs by
workflow — execution evidence, GitHub sync, the lifecycle status flip — stays
with the caller so it runs through the item's own gates.

Rationale and portability constraints: ``docs/archive/decisions/
standalone-item-merge.md``.
"""

from __future__ import annotations

import io
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Sequence

from yoke_contracts.api.function_call import TargetRef
from yoke_core.api.service_client_structured_api_adapter import call_dispatcher

# Exit code for a merge the engine refused because another session holds the
# merge lock. Mirrors the engine's own retryable class so callers can
# distinguish "try again later" from "this merge is wrong".
RECOVERABLE_MERGE_LOCK_EXIT_CODE = 6


@dataclass(frozen=True)
class StandaloneMergeOutcome:
    """What one standalone merge attempt produced."""

    ok: bool
    exit_code: int
    already_merged: bool
    commit_sha: str = ""
    merge_sha: str = ""
    touched_files: tuple[str, ...] = ()
    pushed: bool = False
    error: str = ""
    output: str = ""
    warnings: tuple[str, ...] = field(default=())


def _git(repo_root: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo_root), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _git_out(repo_root: str, *args: str) -> str:
    result = _git(repo_root, *args)
    return result.stdout.strip() if result.returncode == 0 else ""


def _branch_exists(repo_root: str, branch: str) -> bool:
    return _git(
        repo_root, "rev-parse", "--verify", f"refs/heads/{branch}"
    ).returncode == 0


def _is_ancestor(repo_root: str, branch: str, target: str) -> bool:
    return _git(
        repo_root, "merge-base", "--is-ancestor", branch, target
    ).returncode == 0


def _changed_files(repo_root: str, branch: str, target: str) -> tuple[str, ...]:
    """Files the branch changed relative to where it left the base branch."""
    base = _git_out(repo_root, "merge-base", target, branch)
    if not base:
        return ()
    listing = _git_out(repo_root, "diff", "--name-only", base, branch)
    return tuple(line.strip() for line in listing.splitlines() if line.strip())


def _has_remote(repo_root: str) -> bool:
    return bool(_git_out(repo_root, "remote"))


def _publish(repo_root: str, target: str) -> tuple[bool, str]:
    """Push the merged base branch. A failure never unwinds the merge."""
    if not _has_remote(repo_root):
        return False, ""
    pushed = _git(repo_root, "push", "origin", target)
    if pushed.returncode == 0:
        return True, ""
    detail = (pushed.stderr or pushed.stdout or "").strip()
    return False, (
        f"merge landed locally but publishing '{target}' failed: {detail}"
    )


def _run_merge_engine(
    *,
    branch: str,
    target: str,
    local_merge: bool,
) -> tuple[int, str]:
    """Run the merge engine with the standalone permission, capturing output."""
    from yoke_core.engines.merge_worktree import MergeArgs, run as merge_run

    captured = io.StringIO()
    saved_stdout = sys.stdout

    class _Tee:
        def write(self, text: str) -> int:
            saved_stdout.write(text)
            captured.write(text)
            return len(text)

        def flush(self) -> None:
            saved_stdout.flush()

    sys.stdout = _Tee()
    try:
        exit_code = merge_run(
            MergeArgs(
                branch=branch,
                target=target,
                epic_ref=None,
                local_merge=local_merge,
                standalone=True,
            )
        )
    finally:
        sys.stdout = saved_stdout
    return exit_code, captured.getvalue()


def stamp_merged_at(item_id: int) -> Optional[str]:
    """Record when the branch landed. Returns an error string on failure."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    response = call_dispatcher(
        function_id="done_transition.populate_merged_at",
        target=TargetRef(kind="item", item_id=int(item_id)),
        payload={"merged_at": now},
    )
    if response.success:
        return None
    return (
        response.error.message if response.error is not None
        else "merged_at write failed"
    )


def merge_standalone_branch(
    *,
    item_id: int,
    branch: str,
    target: str,
    repo_root: str,
    local_merge: bool = True,
) -> StandaloneMergeOutcome:
    """Land one standalone item branch on ``target`` and stamp the item.

    Idempotent: a branch already contained by ``target`` reports
    ``already_merged`` and still stamps ``merged_at``, so a retry after a
    partial run converges instead of refusing.

    Merge telemetry (``MergeEngineStarted`` and its outcome) is emitted by the
    engine this delegates to, so a standalone merge is visible in the events
    ledger for the same reason an epic-lane merge is.
    """
    if not _branch_exists(repo_root, branch):
        return StandaloneMergeOutcome(
            ok=False,
            exit_code=1,
            already_merged=False,
            error=f"branch '{branch}' does not exist in {repo_root}",
        )

    commit_sha = _git_out(repo_root, "rev-parse", branch)
    touched = _changed_files(repo_root, branch, target)
    already = _is_ancestor(repo_root, branch, target)

    exit_code = 0
    output = ""
    if not already:
        exit_code, output = _run_merge_engine(
            branch=branch, target=target, local_merge=local_merge,
        )
        if exit_code != 0:
            return StandaloneMergeOutcome(
                ok=False,
                exit_code=exit_code,
                already_merged=False,
                commit_sha=commit_sha,
                touched_files=touched,
                error=(
                    "merge lock held by another session; retry once it clears"
                    if exit_code == RECOVERABLE_MERGE_LOCK_EXIT_CODE
                    else f"merge engine exited {exit_code}"
                ),
                output=output,
            )

    merge_sha = _git_out(repo_root, "rev-parse", target)
    warnings: list[str] = []
    pushed, push_warning = _publish(repo_root, target)
    if push_warning:
        warnings.append(push_warning)
    stamp_error = stamp_merged_at(item_id)
    if stamp_error:
        warnings.append(f"merged_at not recorded: {stamp_error}")
    return StandaloneMergeOutcome(
        ok=True,
        exit_code=0,
        already_merged=already,
        commit_sha=commit_sha,
        merge_sha=merge_sha,
        touched_files=touched,
        pushed=pushed,
        output=output,
        warnings=tuple(warnings),
    )


def sync_item_to_github(item_id: int) -> Optional[str]:
    """Mirror the item to GitHub when its project's sync mode allows it.

    The sync owner already skips projects that do not mirror, so this call is
    unconditional; the return value is advisory and never unwinds a merge.
    """
    response = call_dispatcher(
        function_id="items.github_sync",
        target=TargetRef(kind="item", item_id=int(item_id)),
        payload={},
    )
    if response.success:
        return None
    return (
        response.error.message if response.error is not None
        else "GitHub sync failed"
    )


def resolve_touched_files(
    repo_root: str, branch: str, target: str,
) -> Sequence[str]:
    """Public read of the branch's changed-file set for evidence callers."""
    return _changed_files(repo_root, branch, target)


__all__ = [
    "RECOVERABLE_MERGE_LOCK_EXIT_CODE",
    "StandaloneMergeOutcome",
    "merge_standalone_branch",
    "resolve_touched_files",
    "stamp_merged_at",
    "sync_item_to_github",
]
