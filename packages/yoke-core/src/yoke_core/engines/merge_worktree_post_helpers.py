"""Post-merge helper functions for the merge-worktree engine.

Contains:
  - Post-merge verification and cleanup  (_post_merge_cleanup)
  - Schema refresh                       (_schema_refresh)
  - Yoke state dir resolution          (_yoke_state_dir)
  - View regeneration                    (_regenerate_views, _regenerate_views_or_exit5)
  - Target branch enforcement            (_ensure_target_branch)

Local target sync lives in ``merge_worktree_local_sync`` and is
re-exported here for callers using the legacy import path.

These are private helpers; callers should import from
``merge_worktree_post`` which preserves the public import surface.
"""

from __future__ import annotations

import os
from pathlib import Path

from yoke_core.engines.merge_worktree_prepare import (
    MergeContext,
)
from yoke_core.engines.merge_worktree_local_sync import (
    _sync_local_target,  # noqa: F401  -- re-exported for legacy import path
)


# ---------------------------------------------------------------------------
# Lazy parent import helper (mirrors the one in merge_worktree_post)
# ---------------------------------------------------------------------------

def _parent():
    """Return the parent module (merge_worktree) for shared utility access."""
    from yoke_core.engines import merge_worktree as _mw
    return _mw


def _chdir_out_of_doomed_worktree(ctx: MergeContext) -> None:
    """If the Python process's cwd is inside the worktree we are about to
    delete, chdir to ``ctx.repo_root`` so subsequent ``os.getcwd()`` calls
    (in particular the DB-path resolver) do not raise ``FileNotFoundError``.
    """
    if not ctx.worktree_path or not ctx.repo_root:
        return
    try:
        current = os.getcwd()
    except OSError:
        current = ""
    try:
        wt_real = os.path.realpath(ctx.worktree_path)
    except OSError:
        return
    current_real = os.path.realpath(current) if current else ""
    if current_real == wt_real or current_real.startswith(wt_real + os.sep):
        try:
            os.chdir(ctx.repo_root)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Post-merge cleanup
# ---------------------------------------------------------------------------



def _schema_refresh(ctx: MergeContext) -> None:
    """Run schema refresh after merge."""
    mw = _parent()
    _print = mw._print
    _run_python_module = mw._run_python_module

    _print("")
    _print("[schema-gate] Running schema refresh...")
    _run_python_module("yoke_core.domain.schema", ["init"], capture=True)
    _run_python_module("yoke_core.domain.shepherd", ["init"], capture=True)
    _print("[schema-gate] Schema refresh complete.")


def _yoke_state_dir(ctx: MergeContext) -> Path:
    """Return the project-local Yoke artifact dir -- ``<repo>/.yoke``.

    three path concepts must stay distinct in the merge path,
    and collapsing any two of them caused the 2026-04-11 exit-1 incident:

    - ``ctx.repo_root`` -- **project** repo root.  May be rewritten to a
      non-``yoke`` project repo during ``resolve_context()``.
    - ``ctx.yoke_repo_root`` / ``YOKE_REPO_ROOT`` output line -- the
      **Yoke control-repo** root.  ``done_transition`` parses this from
      engine stdout to re-locate the Yoke repo after a cross-project
      merge; its meaning is an output contract and must not be
      repurposed.
    - The Yoke **artifact dir** -- ``<control-repo>/.yoke``. This is
      where project-local generated views such as ``BOARD.md`` live.
      Post-merge view regeneration targets the artifact dir contract,
      NOT the control-repo root.

    Resolution routes through ``rebuild_board.resolve_main_repo_root`` so
    that the ``.worktrees/YOK-N`` -> main-repo stripping is identical to
    the one ``rebuild_board`` applies internally -- both call sites end
    up pointing at the same state dir even when the engine is entered
    from inside a worktree.
    """
    from yoke_core.domain import rebuild_board

    main_repo = rebuild_board.resolve_main_repo_root(ctx.yoke_repo_root)
    return main_repo / ".yoke"


def _regenerate_views(ctx: MergeContext) -> None:
    """Regenerate DB-sourced views after merge.

    Only board rebuild remains as the active view regeneration step.

    Runs in a subprocess rather than importing ``rebuild_board`` in-process
    because the git merge has just rewritten ``runtime/api/domain/*.py`` on
    disk, and the parent interpreter may hold pre-merge entries in
    ``sys.modules`` (loaded during pre-merge ``_emit_merge_event`` calls via
    ``events_writes``). Any post-merge ``from X import NEW_SYMBOL`` against a
    cached module object raises ``ImportError``. A fresh interpreter always
    sees the post-merge source on disk.
    """
    # Test-only hook: black-box harness for the exit-5
    # post-merge-cleanup path.  Production sessions never set this env
    # var; see ``runtime/api/test_merge_worktree_full.py`` for usage.
    if os.environ.get("YOKE_MERGE_TEST_FORCE_REGEN_FAILURE") == "1":
        raise RuntimeError(
            "YOKE_MERGE_TEST_FORCE_REGEN_FAILURE: forced post-merge "
            "view regeneration failure (test hook)"
        )

    mw = _parent()
    _print = mw._print
    _run_python_module = mw._run_python_module

    _print("")
    _print("Regenerating DB-sourced views...")
    result = _run_python_module(
        "yoke_core.domain.rebuild_board",
        ["--force", str(ctx.yoke_repo_root)],
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"rebuild_board subprocess exited with code {result.returncode}"
        )


def _regenerate_views_or_exit5(ctx: MergeContext) -> int:
    """Run ``_regenerate_views`` with post-merge-cleanup error class handling.

    exit code 5 means "the merge is already committed on the
    target branch, but post-merge view regeneration or board rebuild
    failed".  This is a cleanup failure class -- item status MUST NOT be
    rolled back because the git/PR merge itself landed.  Returns:

    - ``0`` if regeneration succeeded.
    - ``5`` if regeneration raised.  A precise ``MergeEngineFailed``
      event with ``phase=post_merge_cleanup`` and ``merge_committed=true``
      is emitted here so the events ledger distinguishes this class from
      an ordinary pre-merge failure.  The generic
      ``MergeEngineFailed`` emission in ``run()``'s ``finally`` block is
      suppressed for exit 5 to avoid double-logging.
    """
    mw = _parent()
    _print = mw._print
    _emit_merge_event = mw._emit_merge_event

    try:
        # Route through parent so monkeypatch on merge_worktree._regenerate_views
        # is honored by test harness.
        mw._regenerate_views(ctx)
        return 0
    except Exception as exc:
        _emit_merge_event(
            "MergeEngineFailed",
            severity="ERROR",
            outcome="failure",
            item_id=ctx.item_id,
            context={
                "branch": ctx.args.branch,
                "target": ctx.args.target,
                "epic_id": ctx.epic_id,
                "phase": "post_merge_cleanup",
                "merge_committed": True,
                "exit_code": 5,
                "error_type": type(exc).__name__,
                "error": str(exc),
            },
        )
        _print("", err=True)
        _print(
            "Error: post-merge view regeneration failed after "
            f"{ctx.args.branch} \u2192 {ctx.args.target} was already committed.",
            err=True,
        )
        _print(
            "Phase: post_merge_cleanup (merge already committed \u2014 do NOT "
            "roll the item back to 'implemented').",
            err=True,
        )
        _print(f"Failure: {type(exc).__name__}: {exc}", err=True)
        _print(
            "Recovery: fix the view-regen / board-rebuild issue, then "
            f"resume with `/yoke usher {(('YOK-' + ctx.item_id) if ctx.item_id else ctx.args.branch)}`.",
            err=True,
        )
        return 5


def _ensure_target_branch(ctx: MergeContext) -> None:
    """Ensure the main repo is on the target branch."""
    mw = _parent()
    _print = mw._print
    _run_git = mw._run_git

    current = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=ctx.repo_root, capture=True)
    if current.returncode == 0:
        branch = current.stdout.strip()
        if branch and branch != ctx.args.target and branch != "HEAD":
            _print(f"Warning: Main repo is on '{branch}', not '{ctx.args.target}'. Switching.", err=True)
            _run_git(["checkout", ctx.args.target], cwd=ctx.repo_root, capture=True)

from yoke_core.engines.merge_worktree_cleanup import _post_merge_cleanup  # noqa: E402,F401
