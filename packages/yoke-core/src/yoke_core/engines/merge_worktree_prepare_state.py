"""Dirty-state and setup helpers for merge-worktree preparation."""

from __future__ import annotations

from typing import Optional, Tuple

from yoke_core.domain.classify_dirty_files import (
    classify_dirty_files,
    is_yoke_managed_pattern,
)
from yoke_core.engines.merge_worktree_prepare import MergeContext, _matches_glob


def _parent():
    from yoke_core.engines import merge_worktree as _mw
    return _mw

def check_and_clean_root_dirty_state(ctx: MergeContext) -> Optional[Tuple[int, str]]:
    """Classify and handle dirty files in repo root. Returns (4, msg) if user files block."""
    mw = _parent()
    _print = mw._print
    _run_git = mw._run_git

    yoke_files, user_files = classify_dirty_files(
        repo_path=ctx.repo_root,
        exclude_worktrees=True,
    )
    if not yoke_files and not user_files:
        return None

    if user_files:
        _print("", err=True)
        _print("Error: Repo root has uncommitted user-authored files.", err=True)
        for uf in user_files:
            _print(f"  - {uf}", err=True)
        return (4, "user-authored files in repo root")

    if yoke_files:
        _print("Auto-committing Yoke-managed files before merge...", err=True)
        for sf in yoke_files:
            _run_git(["add", sf], cwd=ctx.repo_root)
        result = _run_git(
            ["commit", "-m", f"chore: auto-commit Yoke bookkeeping before merge [{ctx.args.branch}]"],
            cwd=ctx.repo_root, capture=True,
        )
        if result.returncode != 0:
            _print("Error: Auto-commit of Yoke-managed files failed.", err=True)
            return (4, "auto-commit failed")
        _print("Auto-committed Yoke bookkeeping files.", err=True)

    return None


def prune_agent_worktrees(repo_root: str, target: str = "main") -> None:
    """Prune only DB-owned terminal work proven merged into ``target``."""
    from yoke_core.engines.merge_worktree_safe_prune import (
        prune_managed_worktrees,
    )

    prune_managed_worktrees(parent=_parent(), repo_root=repo_root, target=target)


def extract_generated_files(ctx: MergeContext) -> list[str]:
    """Extract generated files list from epic body for auto-resolve."""
    mw = _parent()
    if not ctx.epic_id:
        return []

    conn = None
    try:
        conn = mw._connect()
        from yoke_core.domain.render_body import build_body
        rendered = build_body(conn, int(ctx.epic_id)) or ""
        if not rendered:
            return []

        body = rendered
        generated = []
        in_section = False
        in_generated = False
        for line in body.splitlines():
            if line.startswith(f"## Worktree: {ctx.args.branch}"):
                in_section = True
                in_generated = False
            elif line.startswith("## Worktree: "):
                in_section = False
                in_generated = False
            elif line.startswith("## "):
                in_section = False
                in_generated = False
            elif "Generated files" in line and in_section:
                in_generated = True
            elif in_generated and "- " in line:
                gf = line.strip().lstrip("- ").strip()
                if gf:
                    generated.append(gf)

        return generated
    except Exception:  # noqa: BLE001 - generated-file hints are advisory.
        return []
    finally:
        if conn is not None:
            conn.close()


def _pre_merge_integration(ctx: MergeContext) -> None:
    """Bring worktree branch up to date with origin/target before merge."""
    mw = _parent()
    _print = mw._print
    _run_git = mw._run_git

    cwd = ctx.worktree_path
    mb = _run_git(
        ["merge-base", "HEAD", f"origin/{ctx.args.target}"], cwd=cwd, capture=True
    )
    if mb.returncode != 0 or not mb.stdout.strip():
        return

    behind = _run_git(
        ["rev-list", "--count", f"{mb.stdout.strip()}..origin/{ctx.args.target}"],
        cwd=cwd, capture=True,
    )
    behind_count = int(behind.stdout.strip()) if behind.returncode == 0 and behind.stdout.strip() else 0

    if behind_count <= 0:
        return

    _print(f"Integrating origin/{ctx.args.target} into worktree branch ({behind_count} commit(s) behind)...")
    merge_result = _run_git(
        ["merge", f"origin/{ctx.args.target}", "--no-edit"], cwd=cwd, capture=True
    )

    if merge_result.returncode != 0:
        # Try auto-resolving generated files only
        conflicts = _run_git(["diff", "--name-only", "--diff-filter=U"], cwd=cwd, capture=True)
        if conflicts.stdout.strip():
            all_auto = True
            for cf in conflicts.stdout.strip().splitlines():
                if not _matches_glob(cf, ctx.yoke_gen_files):
                    all_auto = False
                    break
            if all_auto:
                for cf in conflicts.stdout.strip().splitlines():
                    _run_git(["checkout", "--theirs", cf], cwd=cwd, capture=True)
                    _run_git(["add", cf], cwd=cwd, capture=True)
                _run_git(["commit", "--no-edit"], cwd=cwd, capture=True)
                _print("Pre-merge integration: auto-resolved generated file conflicts.")
            else:
                _run_git(["merge", "--abort"], cwd=cwd, capture=True)
                _print("Pre-merge integration: non-trivial conflicts, deferring to main merge flow.")
    else:
        _print("Pre-merge integration: success.")


def _stash_classify_gate(ctx: MergeContext) -> Optional[Tuple[int, str]]:
    """Safety stash and classify dirty state. Returns (4, msg) if user files at risk."""
    mw = _parent()
    _print = mw._print
    _run_git = mw._run_git

    cwd = ctx.worktree_path
    status = _run_git(["status", "--porcelain"], cwd=cwd, capture=True)
    if not status.stdout.strip():
        return None

    _print(f"Creating safety stash: yoke-pre-rebase-{ctx.args.branch}")
    _run_git(["stash", "push", "--include-untracked", "-m", f"yoke-pre-rebase-{ctx.args.branch}"],
             cwd=cwd, capture=True)
    _run_git(["stash", "apply"], cwd=cwd, capture=True)

    # Classify
    dirty_tracked = _run_git(["diff", "--name-only"], cwd=cwd, capture=True)
    dirty_untracked = _run_git(["ls-files", "--others", "--exclude-standard"], cwd=cwd, capture=True)

    all_tracked = dirty_tracked.stdout.strip().splitlines() if dirty_tracked.stdout.strip() else []
    all_untracked = dirty_untracked.stdout.strip().splitlines() if dirty_untracked.stdout.strip() else []

    user_files = [f for f in all_tracked + all_untracked if not is_yoke_managed_pattern(f)]

    if user_files:
        _print("", err=True)
        _print("Error: Worktree has dirty files that are NOT Yoke-managed.", err=True)
        for uf in user_files:
            _print(f"  - {uf}", err=True)
        _print(f"Your work is safe in stash: yoke-pre-rebase-{ctx.args.branch}", err=True)
        return (4, "user-authored files at risk")

    # Discard yoke-managed tracked modifications
    yoke_tracked = [f for f in all_tracked if is_yoke_managed_pattern(f)]
    for sf in yoke_tracked:
        _run_git(["checkout", "--", sf], cwd=cwd, capture=True)

    return None
