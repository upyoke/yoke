"""Rebase and merge-commit execution for merge-worktree."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Optional, Tuple

from yoke_core.engines.merge_worktree_conflicts import auto_resolve_conflicts
from yoke_core.engines.merge_worktree_prepare import MergeContext


def _parent():
    from yoke_core.engines import merge_worktree as _mw
    return _mw

def do_rebase_or_merge(ctx: MergeContext) -> Optional[Tuple[int, str]]:
    """Execute the actual rebase or merge-commit strategy.

    Returns (exit_code, msg) on failure, None on success.
    """
    from yoke_core.domain import project_settings

    mw = _parent()
    _print = mw._print
    _run_git = mw._run_git

    cwd = ctx.worktree_path
    merge_conflict_threshold = project_settings.get_project_int(
        ctx.repo_root, "merge_conflict_threshold",
    )

    # Check for merge commits
    merge_base = _run_git(
        ["merge-base", "HEAD", f"origin/{ctx.args.target}"], cwd=cwd, capture=True
    )
    original_merge_count = 0
    if merge_base.returncode == 0 and merge_base.stdout.strip():
        mc_result = _run_git(
            ["log", "--oneline", "--merges", f"{merge_base.stdout.strip()}..HEAD"],
            cwd=cwd, capture=True,
        )
        if mc_result.returncode == 0:
            original_merge_count = len(mc_result.stdout.strip().splitlines()) if mc_result.stdout.strip() else 0

    rebase_succeeded = False

    if original_merge_count > 0:
        _print(f"")
        _print(f"Branch has {original_merge_count} merge commit(s) \u2014 skipping rebase.")
        _print("Using merge strategy instead...")
        ctx.used_merge_fallback = True
    else:
        _print("")
        _print(f"Rebasing {ctx.args.branch} onto {ctx.args.target}...")

        rebase_result = _run_git(
            ["rebase", f"origin/{ctx.args.target}"], cwd=cwd, capture=True
        )

        if rebase_result.returncode == 0:
            rebase_succeeded = True
        else:
            # Multi-commit rebase loop
            rebase_pass = 0
            max_passes = 50
            while rebase_pass < max_passes:
                rebase_pass += 1

                rc, infos = auto_resolve_conflicts(ctx)

                if rc == 0:
                    cont = subprocess.run(
                        ["git", "rebase", "--continue"],
                        cwd=cwd, capture_output=True, text=True,
                        env={**os.environ, "GIT_EDITOR": "true"},
                    )
                    if cont.returncode == 0:
                        _print(f"Rebase completed after {rebase_pass} auto-resolve pass(es).")
                        rebase_succeeded = True
                        break
                    if rebase_pass >= merge_conflict_threshold:
                        _print(f"")
                        _print(f"Rebase produced {rebase_pass} conflict passes (threshold: {merge_conflict_threshold}).")
                        _print("Falling back to merge-commit strategy...")
                        _run_git(["rebase", "--abort"], cwd=cwd, capture=True)
                        break
                elif rc == 2:
                    skip = _run_git(["rebase", "--skip"], cwd=cwd, capture=True)
                    if skip.returncode == 0:
                        _print(f"Rebase completed after {rebase_pass} pass(es) (with empty commit skip).")
                        rebase_succeeded = True
                        break
                    if rebase_pass >= merge_conflict_threshold:
                        _run_git(["rebase", "--abort"], cwd=cwd, capture=True)
                        break
                else:
                    _print("Rebase hit non-auto-resolvable conflict(s). Falling back to merge-commit...")
                    _run_git(["rebase", "--abort"], cwd=cwd, capture=True)
                    break

            if rebase_pass >= max_passes:
                _run_git(["rebase", "--abort"], cwd=cwd, capture=True)

    # Merge-commit fallback
    if not rebase_succeeded:
        ctx.used_merge_fallback = True
        _print("")
        _print(f"Attempting merge-commit: git merge origin/{ctx.args.target}...")

        merge_result = _run_git(
            ["merge", f"origin/{ctx.args.target}", "--no-edit"], cwd=cwd, capture=True
        )

        if merge_result.returncode != 0:
            rc, infos = auto_resolve_conflicts(ctx)
            if rc == 0:
                _print("All merge-commit conflicts auto-resolved.")
                _run_git(["commit", "--no-edit"], cwd=cwd, capture=True)
            elif rc == 2:
                _print("Merge reported failure but no conflict markers found \u2014 committing.")
                _run_git(["commit", "--no-edit"], cwd=cwd, capture=True)
            else:
                # Emit structured conflict output
                _print("", err=True)
                _print("\u2554\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2557", err=True)
                _print("\u2551  MERGE CONFLICT \u2014 agent resolution possible                \u2551", err=True)
                _print("\u255a\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u255d", err=True)
                _print("", err=True)
                for info in infos:
                    _print(f"  CONFLICT|{info.path}|{info.classification}", err=True)
                _run_git(["merge", "--abort"], cwd=cwd, capture=True)
                return (3, "merge conflicts require agent resolution")

        _print("Merge-commit succeeded.")

        # Regenerate package-lock.json if needed
        if (Path(cwd) / "package.json").is_file():
            _print("Regenerating package-lock.json...")
            subprocess.run(["npm", "install"], cwd=cwd, capture_output=True)

    return None
