"""Bind a standalone lane to its recorded merge source, and back again."""

from __future__ import annotations

from yoke_core.engines.merge_worktree_prepare import MergeContext


def bind_recorded_source(ctx: MergeContext, current_branch_sha: str) -> str:
    """Return an error, or reconcile the lane ref with its recorded HEAD.

    ``source_sha`` is the control plane's last-recorded commit for this
    lane -- the commit-bound identity a caller resolved before invoking the
    engine. When the checked-out branch already contains that commit as an
    ancestor, the branch has moved on since the record was taken (most
    often this engine's own prior run advancing HEAD and being interrupted
    before it could persist that fact -- see
    :func:`record_lane_head_after_merge`) and is left untouched: proven
    continuation of the recorded source always outranks a stale record.
    When the recorded commit is itself ahead of an unmoved branch, the
    branch is fast-forwarded to it, preserving the recovery this function
    originally existed for. Anything else -- unrelated history on both
    sides -- is refused with a diagnostic instead of blindly rewound,
    because ``update-ref`` does not touch the index or working tree of
    whichever worktree has this branch checked out, so an unsynchronized
    rewind strands that checkout dirty against a branch tip it never saw
    move.
    """
    source_sha = ctx.args.source_sha
    if not source_sha:
        return ""
    from yoke_core.engines import merge_worktree as mw

    source = mw._run_git(
        ["rev-parse", "--verify", f"{source_sha}^{{commit}}"],
        cwd=ctx.repo_root,
        capture=True,
    )
    if source.returncode != 0:
        return f"recorded lane HEAD {source_sha} is not a commit"
    if source_sha == current_branch_sha:
        return ""
    if _is_ancestor(ctx, source_sha, current_branch_sha):
        return ""
    if not _is_ancestor(ctx, current_branch_sha, source_sha):
        worktree = ctx.worktree_path or ctx.repo_root
        return (
            f"lane {ctx.args.branch!r} at {current_branch_sha[:12]} and its "
            f"recorded HEAD {source_sha[:12]} have diverged; inspect with "
            f"`git -C {worktree} log --oneline {source_sha}..{current_branch_sha}` "
            "and once the correct side is confirmed, resync the record with "
            f"`yoke project snapshot sync --head-only {worktree}`"
        )
    rebound = mw._run_git(
        [
            "update-ref",
            f"refs/heads/{ctx.args.branch}",
            source_sha,
            current_branch_sha,
        ],
        cwd=ctx.repo_root,
        capture=True,
    )
    if rebound.returncode != 0:
        return (
            "lane branch changed while binding its recorded HEAD; "
            "retry after the competing update stops"
        )
    return ""


def _is_ancestor(ctx: MergeContext, maybe_ancestor: str, descendant: str) -> bool:
    from yoke_core.engines import merge_worktree as mw

    result = mw._run_git(
        ["merge-base", "--is-ancestor", maybe_ancestor, descendant],
        cwd=ctx.repo_root,
        capture=True,
    )
    return result.returncode == 0


def record_lane_head_after_merge(ctx: MergeContext) -> None:
    """Persist HEAD the moment the engine's own rebase/merge advances it.

    Runs right after ``do_rebase_or_merge`` succeeds, before push, tests, or
    CI can be interrupted, so a retry's recorded source is never a step
    behind work this engine already completed -- the gap
    :func:`bind_recorded_source` above tolerates, closed at the source.
    Reuses the same head-only snapshot sync the git post-commit hook drives
    for an ordinary commit; best-effort like that hook, so a sync hiccup
    here never fails an otherwise-landed merge.
    """
    from yoke_cli.commands.adapters.project_snapshot import (
        sync_local_snapshot_for_write,
    )

    sync_local_snapshot_for_write(
        project=ctx.project or "yoke",
        repo_root=ctx.worktree_path or ctx.repo_root,
        integration_target=None,
        session_id=None,
        head_only=True,
    )


__all__ = ["bind_recorded_source", "record_lane_head_after_merge"]
