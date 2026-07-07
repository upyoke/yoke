"""Local target-branch sync after a successful PR merge.

Extracted from ``merge_worktree_post_helpers`` so the post-helpers file
stays under the 350-line cap and so the sync primitive has a focused
home.

Two strategies, picked at runtime based on which branch is currently
checked out in the main repo:

- **Target not checked out** (the typical worktree case): a single
  ``git fetch origin {target}:{target}`` updates the local ref directly
  without touching the working tree.
- **Target checked out**: two explicit steps -- ``git fetch origin
  {target}`` and then ``git merge --ff-only origin/{target}``.  The
  earlier shape ran ``git pull --ff-only origin {target}`` which can
  surface ``Cannot fast-forward to multiple branches`` when more than
  one ref shares the local checkout's tracking config.  The explicit
  fetch + fast-forward pair is unambiguous and idempotent.

Both strategies are bounded by the ``post_merge_rebase_timeout`` config
key.  Verification afterwards confirms ``local {target}`` matches
``origin/{target}`` -- if it doesn't, the function returns ``False`` and
the caller surfaces the exit-5 ``LocalTargetSyncFailed`` class.
"""

from __future__ import annotations

import subprocess

from yoke_core.engines.merge_worktree_prepare import MergeContext


def _parent():
    """Return the parent module (merge_worktree) for shared utility access."""
    from yoke_core.engines import merge_worktree as _mw
    return _mw


def _sync_local_target(ctx: MergeContext) -> bool:
    """Sync local target branch ref with origin after PR merge.

    Returns ``True`` on success, ``False`` on failure.
    """
    from yoke_core.domain import runtime_settings

    mw = _parent()
    _print = mw._print
    _run_git = mw._run_git
    _git_env = mw._git_env

    _print("")
    _print(f"Syncing local {ctx.args.target} with origin...")

    stashed = False
    status = _run_git(["status", "--porcelain"], cwd=ctx.repo_root, capture=True)
    if status.stdout.strip():
        _print("Stashing dirty files before sync...")
        _run_git(
            ["stash", "push", "--include-untracked", "-m", "yoke-post-merge-sync"],
            cwd=ctx.repo_root,
            capture=True,
        )
        stashed = True

    success = False
    timeout = runtime_settings.get_seconds("post_merge_rebase_timeout", 120)

    current_branch = _run_git(
        ["rev-parse", "--abbrev-ref", "HEAD"], cwd=ctx.repo_root, capture=True,
    )
    checked_out = (
        current_branch.returncode == 0
        and current_branch.stdout.strip() == ctx.args.target
    )

    try:
        if checked_out:
            # Two unambiguous steps: fetch the remote target ref, then
            # fast-forward the checked-out branch onto origin/{target}.
            # Avoids the ``git pull --ff-only origin {target}`` shape
            # which can surface ``Cannot fast-forward to multiple
            # branches`` under some tracking configs.
            fetch = subprocess.run(
                ["git", "fetch", "origin", ctx.args.target],
                cwd=ctx.repo_root,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=_git_env(),
            )
            if fetch.returncode != 0:
                sync = fetch
                strategy = "fetch"
            else:
                sync = subprocess.run(
                    ["git", "merge", "--ff-only", f"origin/{ctx.args.target}"],
                    cwd=ctx.repo_root,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    env=_git_env(),
                )
                strategy = "merge --ff-only"
        else:
            # Target is NOT checked out -- direct ref update.  This is the
            # worktree scenario where a pull would update the checked-out
            # feature branch instead of the target.
            sync = subprocess.run(
                ["git", "fetch", "origin",
                 f"{ctx.args.target}:{ctx.args.target}"],
                cwd=ctx.repo_root,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=_git_env(),
            )
            strategy = "fetch"

        if sync.returncode == 0:
            local_ref = _run_git(
                ["rev-parse", ctx.args.target],
                cwd=ctx.repo_root, capture=True,
            )
            origin_ref = _run_git(
                ["rev-parse", f"origin/{ctx.args.target}"],
                cwd=ctx.repo_root, capture=True,
            )
            local_sha = local_ref.stdout.strip() if local_ref.returncode == 0 else ""
            origin_sha = origin_ref.stdout.strip() if origin_ref.returncode == 0 else ""
            if local_sha and origin_sha and local_sha == origin_sha:
                _print(f"Local {ctx.args.target} is now up to date with origin.")
                success = True
            elif local_sha and origin_sha:
                _print(
                    f"Warning: Local {ctx.args.target} ({local_sha[:8]}) "
                    f"does not match origin ({origin_sha[:8]}) after sync.",
                    err=True,
                )
            else:
                _print(
                    f"Warning: Could not verify {ctx.args.target} ref after sync.",
                    err=True,
                )
        else:
            stderr = (sync.stderr or "").strip()
            _print(
                f"Warning: git {strategy} failed "
                f"(exit {sync.returncode}): {stderr}",
                err=True,
            )
    except subprocess.TimeoutExpired:
        _print("Warning: Post-merge sync timed out.", err=True)

    if stashed:
        _print("Restoring stashed files...")
        pop = _run_git(["stash", "pop"], cwd=ctx.repo_root, capture=True)
        if pop.returncode != 0:
            _print("Warning: stash pop had conflicts.", err=True)

    return success
