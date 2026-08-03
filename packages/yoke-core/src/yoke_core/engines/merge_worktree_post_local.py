"""Local merge path for merge-worktree."""

from __future__ import annotations

from yoke_contracts.api.function_call import TargetRef
from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
from yoke_core.engines.merge_worktree_prepare import MergeContext
from yoke_core.engines.merge_worktree_post_helpers import (
    _chdir_out_of_doomed_worktree,
    _schema_refresh,
    _regenerate_views_or_exit5,
    _ensure_target_branch,
)


def _parent():
    from yoke_core.engines import merge_worktree as _mw
    return _mw


def _ensure_snapshot_for_project(ctx: MergeContext) -> None:
    """Pre-warm the path-snapshot cache for the project's HEAD after merge.

    Defense in depth alongside the global ``post-commit`` hook installed
    by ``yoke project install`` (shim owner:
    :mod:`yoke_core.domain.project_install_git_hooks`). Failures here
    are advisory — a snapshot miss does not roll back a successful
    merge; the next activate call will surface a clearer error.
    """
    try:
        import subprocess

        project_id = (
            getattr(ctx.args, "project", None)
            or getattr(ctx, "project_id", None)
            or "yoke"
        )
        # Resolve the freshly-merged HEAD from the local checkout, then relay
        # the path-snapshot write so it lands on the connected control plane
        # (in-process against local Postgres, or over https server-side)
        # rather than opening a bare local connection.
        head = subprocess.run(
            ["git", "-C", str(ctx.repo_root), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=False,
        )
        if head.returncode != 0 or not head.stdout.strip():
            return
        resp = call_dispatcher(
            function_id="project.snapshot.ensure_at",
            target=TargetRef(kind="global"),
            payload={
                "project": str(project_id),
                "commit_sha": head.stdout.strip(),
            },
        )
        if not resp.success:
            detail = (
                resp.error.message if resp.error else "snapshot ensure relay failed"
            )
            _parent()._print(f"  Note: ensure_snapshot_at advisory: {detail}")
    except Exception as exc:  # noqa: BLE001
        try:
            _parent()._print(
                f"  Note: ensure_snapshot_at advisory: {exc}"
            )
        except Exception:  # noqa: BLE001
            pass


def _remove_lane(ctx: MergeContext) -> None:
    """Discard the merged worktree and its branch. Always the last step.

    Removing the lane is destructive to more than git: the merging process may
    be importing its own package source out of that directory, so any module it
    has not yet loaded becomes unresolvable the moment the lane is gone. Every
    step that still needs the lane — and every close-out step that follows this
    one in the caller — must therefore run before this returns.

    Cleanup happens only when the worktree holds no tracked, untracked, or
    ignored material: a local merge proves the branch commits are retained by
    the target, but it does not prove filesystem-only work is safe to discard.
    """
    mw = _parent()
    _print = mw._print
    _run_git = mw._run_git

    if ctx.worktree_path == ctx.repo_root:
        return

    _chdir_out_of_doomed_worktree(ctx)
    from yoke_core.engines.merge_worktree_cleanliness import (
        clean_after_disposable_cache_removal,
    )

    if not clean_after_disposable_cache_removal(_run_git, ctx.worktree_path):
        _print(
            f"WARNING: Preserving dirty or unverifiable worktree: "
            f"{ctx.worktree_path}",
            err=True,
        )
        return

    removed = _run_git(
        ["worktree", "remove", ctx.worktree_path],
        cwd=ctx.repo_root,
        capture=True,
    )
    if removed.returncode != 0:
        _print(
            f"WARNING: Worktree removal refused; preserving branch "
            f"{ctx.args.branch}",
            err=True,
        )
        return

    _print(f"Cleaned up worktree: {ctx.worktree_path}")
    _run_git(["branch", "-d", ctx.args.branch], cwd=ctx.repo_root, capture=True)


def do_local_merge(ctx: MergeContext) -> int:
    """Execute local merge (--local flag). Returns exit code."""
    mw = _parent()
    _print = mw._print
    _run_git = mw._run_git

    _print("")
    _print("Local merge mode \u2014 skipping push/PR/CI pipeline.")

    _print(f"Merging {ctx.args.branch} into local {ctx.args.target}...")
    _run_git(["checkout", ctx.args.target], cwd=ctx.repo_root, capture=True)
    result = _run_git(
        ["merge", "--no-edit", ctx.args.branch], cwd=ctx.repo_root, capture=True
    )
    if result.returncode != 0:
        _print(f"Error: Local merge of {ctx.args.branch} into {ctx.args.target} failed:", err=True)
        if result.stderr:
            _print(result.stderr, err=True)
        _run_git(["merge", "--abort"], cwd=ctx.repo_root, capture=True)
        return 1

    _print(f"Merged {ctx.args.branch} into {ctx.args.target} successfully.")

    # Defense-in-depth: sync the path-snapshot cache for the new HEAD on
    # the integration branch so subsequent activate / boundary callers do
    # not hit a cold-start miss before the post-commit hook has fired (or
    # on fresh clones where the operator has not yet installed the hook).
    _ensure_snapshot_for_project(ctx)

    # Schema refresh
    _schema_refresh(ctx)

    # Regenerate views -- post-merge-cleanup failure after local merge
    # landed is its own exit class.
    regen_exit = _regenerate_views_or_exit5(ctx)

    # Ensure on target branch regardless of regen outcome
    _ensure_target_branch(ctx)

    # Lane removal last: everything above still reads from the worktree, and
    # so does the caller's close-out. See _remove_lane.
    _remove_lane(ctx)

    _print("")
    _print(f"YOKE_REPO_ROOT={ctx.yoke_repo_root}")
    return regen_exit
