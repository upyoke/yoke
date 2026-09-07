"""Post-merge helper functions for the merge-worktree engine.

Contains:
  - Post-merge verification and cleanup  (_post_merge_cleanup)
  - Schema refresh                       (_schema_refresh)
  - Target branch enforcement            (_ensure_target_branch)

Local target sync lives in ``merge_worktree_local_sync`` and is
re-exported here for callers using the legacy import path.

These are private helpers; callers should import from
``merge_worktree_post`` which preserves the public import surface.
"""

from __future__ import annotations

import os

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
    """Run schema refresh after merge.

    Over an https control plane the server owns and converges its own
    schema on boot (``converge_core_schema``); there is no local DB to
    re-converge, and re-converging the server's schema from the client is
    neither possible nor correct, so the refresh is skipped. On a local
    Postgres connection the merge just updated the schema source on disk,
    so the local DB is re-converged in a fresh subprocess exactly as
    before.
    """
    from yoke_core.domain.worktree_create_db import (
        item_worktree_authority_is_https,
    )

    mw = _parent()
    _print = mw._print

    _print("")
    if item_worktree_authority_is_https():
        _print(
            "[schema-gate] Skipping schema refresh over https "
            "(server owns its own schema)."
        )
        return
    _run_python_module = mw._run_python_module
    _print("[schema-gate] Running schema refresh...")
    _run_python_module("yoke_core.domain.schema", ["init"], capture=True)
    _run_python_module("yoke_core.domain.shepherd", ["init"], capture=True)
    _print("[schema-gate] Schema refresh complete.")


def _ensure_target_branch(ctx: MergeContext) -> None:
    """Ensure the main repo is on the target branch."""
    mw = _parent()
    _print = mw._print
    _run_git = mw._run_git

    current = _run_git(
        ["rev-parse", "--abbrev-ref", "HEAD"], cwd=ctx.repo_root, capture=True
    )
    if current.returncode == 0:
        branch = current.stdout.strip()
        if branch and branch != ctx.args.target and branch != "HEAD":
            _print(
                f"Warning: Main repo is on '{branch}', not '{ctx.args.target}'. Switching.",
                err=True,
            )
            _run_git(["checkout", ctx.args.target], cwd=ctx.repo_root, capture=True)


from yoke_core.engines.merge_worktree_cleanup import _post_merge_cleanup  # noqa: E402,F401
