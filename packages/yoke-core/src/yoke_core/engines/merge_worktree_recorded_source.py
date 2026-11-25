"""Bind a standalone lane to its recorded merge source, and back again."""

from __future__ import annotations

import shlex

from yoke_core.domain.merge_context import MergeArgs, MergeContext


def reconcile_epic_source(args: MergeArgs, epic: dict) -> None:
    """Bind the requested epic branch before any comparison uses its SHA."""
    from yoke_core.domain.lane_head_record import reconcile_lane_head
    from yoke_core.domain.standalone_item_merge_lane import active_lanes

    lane = next((row for row in active_lanes(epic) if row.get("branch") == args.branch), None)
    if lane is None:
        return
    project = str((epic.get("project") or {}).get("slug") or "")
    head, error = reconcile_lane_head(project, lane)
    if error:
        raise RuntimeError(error)
    args.source_sha = head or lane.get("commit_sha") or args.source_sha


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
    When the recorded commit is itself ahead of an unmoved branch, it is
    fast-forwarded to -- via ``git merge --ff-only`` in whichever worktree
    has the branch checked out, so ref, index, and files move together
    atomically and git's own safety refuses a dirty or non-fast-forward
    tree, or via ``update-ref`` when the branch is not checked out
    anywhere and there is no worktree to protect. Anything else --
    unrelated history on both sides -- is refused with a diagnostic
    instead of guessed at.
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
        inspect = shlex.join([
            "git", "-C", str(worktree), "log", "--oneline", "--left-right",
            f"{source_sha}...{current_branch_sha}",
        ])
        return (
            f"lane {ctx.args.branch!r} at {current_branch_sha} and its "
            f"recorded HEAD {source_sha} have diverged; inspect with `{inspect}`"
        )
    checked_out_worktree = _checked_out_worktree(ctx)
    if checked_out_worktree:
        fast_forward = mw._run_git(
            ["merge", "--ff-only", source_sha],
            cwd=checked_out_worktree,
            capture=True,
        )
        if fast_forward.returncode != 0:
            detail = (fast_forward.stderr or fast_forward.stdout or "").strip()
            return (
                f"lane {ctx.args.branch!r} is checked out at "
                f"{checked_out_worktree} and could not fast-forward to its "
                f"recorded HEAD: {detail or 'git merge --ff-only refused'}. "
                "Commit or stash uncommitted work there, then retry"
            )
        return ""
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


def _checked_out_worktree(ctx: MergeContext) -> str:
    """Return the worktree with ``ctx.args.branch`` checked out, or ``""``.

    ``ctx.worktree_path`` falls back to ``ctx.repo_root`` even when the
    branch is not checked out anywhere (:func:`merge_worktree_prepare._find_worktree`),
    so this confirms the branch is genuinely there before treating its
    index and files as load-bearing.
    """
    from yoke_core.engines import merge_worktree as mw

    candidate = ctx.worktree_path or ctx.repo_root
    current = mw._run_git(["symbolic-ref", "-q", "HEAD"], cwd=candidate, capture=True)
    if (
        current.returncode == 0
        and current.stdout.strip() == f"refs/heads/{ctx.args.branch}"
    ):
        return candidate
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

    Shares :mod:`yoke_core.domain.lane_head_record` with the QA gate's own
    publish, because both are the same event -- a lane HEAD advanced by a
    rebase or merge this engine ran. A write failure is reported and does not
    fail an otherwise-landed merge.
    """
    from yoke_core.domain import lane_head_record

    mw = _parent()
    checkout_path = ctx.worktree_path or ctx.repo_root
    detail = lane_head_record.record_lane_head(ctx.project, checkout_path)
    if detail:
        mw._print(
            f"warning: could not persist advanced lane HEAD for "
            f"{checkout_path}: {detail}",
            err=True,
        )


def _parent():
    from yoke_core.engines import merge_worktree as _mw

    return _mw


__all__ = ["bind_recorded_source", "record_lane_head_after_merge"]
