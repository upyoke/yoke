"""Local merge path for merge-worktree."""

from __future__ import annotations

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

        from yoke_core.domain import db_helpers
        from yoke_core.domain.path_snapshots import ensure_snapshot_at

        project_id = (
            getattr(ctx.args, "project", None)
            or getattr(ctx, "project_id", None)
            or "yoke"
        )
        head = subprocess.run(
            ["git", "-C", str(ctx.repo_root), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=False,
        )
        if head.returncode != 0 or not head.stdout.strip():
            return
        conn = db_helpers.connect()
        try:
            ensure_snapshot_at(conn, project_id, head.stdout.strip())
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        try:
            _parent()._print(
                f"  Note: ensure_snapshot_at advisory: {exc}"
            )
        except Exception:  # noqa: BLE001
            pass


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

    # Clean up worktree and branch
    if ctx.worktree_path != ctx.repo_root:
        _chdir_out_of_doomed_worktree(ctx)
        _run_git(["worktree", "remove", "--force", ctx.worktree_path], cwd=ctx.repo_root, capture=True)
        _print(f"Cleaned up worktree: {ctx.worktree_path}")
        _run_git(["branch", "-d", ctx.args.branch], cwd=ctx.repo_root, capture=True)

    # Schema refresh
    _schema_refresh(ctx)

    # Regenerate views -- post-merge-cleanup failure after local merge
    # landed is its own exit class.
    regen_exit = _regenerate_views_or_exit5(ctx)

    # Ensure on target branch regardless of regen outcome
    _ensure_target_branch(ctx)

    _print("")
    _print(f"YOKE_REPO_ROOT={ctx.yoke_repo_root}")
    return regen_exit
