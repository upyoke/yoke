"""Conflict classification and trial-merge helpers."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Optional, Tuple

from yoke_core.domain.project_scratch_dir import scratch_subdir
from yoke_core.engines.merge_worktree_prepare import ConflictInfo, MergeContext


def _parent():
    from yoke_core.engines import merge_worktree as _mw
    return _mw

def classify_conflict(
    filepath: str,
    ctx: MergeContext,
) -> ConflictInfo:
    """Classify a single conflicting file."""
    import fnmatch

    # Check generated files
    if filepath in ctx.generated_files:
        return ConflictInfo(filepath, "generated (auto)", True)

    # Check doc files
    for pattern in ctx.doc_files:
        if fnmatch.fnmatch(filepath, pattern):
            if filepath in ctx.branch_changed_files:
                return ConflictInfo(filepath, "doc (branch-modified, manual)", False)
            return ConflictInfo(filepath, "doc (auto)", True)

    # Check yoke-gen files
    for pattern in ctx.yoke_gen_files:
        if fnmatch.fnmatch(filepath, pattern):
            return ConflictInfo(filepath, "yoke-gen (auto)", True)

    # Check additive conflict — route through parent module so
    # monkeypatch on merge_worktree.is_additive_conflict is honored.
    _is_additive = _parent().is_additive_conflict
    if _is_additive(filepath, ctx.worktree_path):
        return ConflictInfo(filepath, "additive (auto)", True)

    return ConflictInfo(filepath, "overlapping (needs agent judgement)", False)


def is_additive_conflict(filepath: str, cwd: str) -> bool:
    """Check if a conflict is purely additive (both sides only added lines)."""
    mw = _parent()
    _run_git = mw._run_git

    # Get the three merge stages
    base = _run_git(["show", f":1:{filepath}"], cwd=cwd, capture=True)
    ours = _run_git(["show", f":2:{filepath}"], cwd=cwd, capture=True)
    theirs = _run_git(["show", f":3:{filepath}"], cwd=cwd, capture=True)

    if any(r.returncode != 0 for r in (base, ours, theirs)):
        return False

    base_lines = set(base.stdout.splitlines())
    ours_lines = set(ours.stdout.splitlines())
    theirs_lines = set(theirs.stdout.splitlines())

    # Both sides must only have additions relative to base (no deletions)
    ours_removed = base_lines - ours_lines
    theirs_removed = base_lines - theirs_lines

    if ours_removed or theirs_removed:
        return False

    # At least one side must have additions
    ours_added = ours_lines - base_lines
    theirs_added = theirs_lines - base_lines

    if not ours_added and not theirs_added:
        return False

    return True


def resolve_conflict(info: ConflictInfo, ctx: MergeContext) -> bool:
    """Resolve a single auto-resolvable conflict. Returns True on success."""
    mw = _parent()
    _run_git = mw._run_git
    _print = mw._print
    cwd = ctx.worktree_path

    if info.classification.startswith("generated"):
        _run_git(["checkout", "--theirs", info.path], cwd=cwd, capture=True)
        _run_git(["add", info.path], cwd=cwd, capture=True)
        _print(f"Auto-resolving generated file conflict: {info.path}...")
        return True

    if info.classification == "doc (auto)":
        # Keep main's version (ours during rebase)
        _run_git(["checkout", "--ours", info.path], cwd=cwd, capture=True)
        _run_git(["add", info.path], cwd=cwd, capture=True)
        _print(f"Auto-resolving doc file conflict: {info.path} (keeping main's version)...")
        return True

    if info.classification.startswith("yoke-gen"):
        _run_git(["checkout", "--theirs", info.path], cwd=cwd, capture=True)
        _run_git(["add", info.path], cwd=cwd, capture=True)
        _print(f"Auto-resolving generated view conflict: {info.path}...")
        return True

    if info.classification.startswith("additive"):
        return _resolve_additive_conflict(info.path, cwd)

    return False


def _resolve_additive_conflict(filepath: str, cwd: str) -> bool:
    """Resolve an additive conflict via git merge-file --union."""
    mw = _parent()
    _run_git = mw._run_git
    _print = mw._print

    with scratch_subdir(prefix="merge-additive") as tmpdir:
        base_path = os.path.join(tmpdir, "base")
        ours_path = os.path.join(tmpdir, "ours")
        theirs_path = os.path.join(tmpdir, "theirs")

        base = _run_git(["show", f":1:{filepath}"], cwd=cwd, capture=True)
        ours = _run_git(["show", f":2:{filepath}"], cwd=cwd, capture=True)
        theirs = _run_git(["show", f":3:{filepath}"], cwd=cwd, capture=True)

        if any(r.returncode != 0 for r in (base, ours, theirs)):
            return False

        Path(base_path).write_text(base.stdout)
        Path(ours_path).write_text(ours.stdout)
        Path(theirs_path).write_text(theirs.stdout)

        # git merge-file --union modifies ours_path in-place
        subprocess.run(
            ["git", "merge-file", "--union", ours_path, base_path, theirs_path],
            capture_output=True, text=True,
        )

        result_text = Path(ours_path).read_text()

        # Safety: check for conflict markers
        for marker in ("<<<<<<< ", "=======", ">>>>>>> "):
            if marker in result_text:
                _print(f"  Additive resolver: conflict markers remain — aborting for {filepath}")
                return False

        # Verify content preservation
        ours_orig = ours.stdout
        theirs_orig = theirs.stdout
        base_orig = base.stdout
        base_set = set(base_orig.splitlines())

        for source, label in [(ours_orig, "ours"), (theirs_orig, "theirs")]:
            for line in source.splitlines():
                if line.strip() and line not in base_set:
                    if line not in result_text:
                        _print(f"  Additive resolver: content from {label} lost — aborting for {filepath}")
                        return False

        # Apply resolved content
        target = os.path.join(cwd, filepath)
        Path(target).write_text(result_text)
        _run_git(["add", filepath], cwd=cwd, capture=True)
        _print(f"Auto-resolving additive conflict: {filepath} (both sides preserved via union merge)")
        return True


def auto_resolve_conflicts(ctx: MergeContext) -> Tuple[int, list[ConflictInfo]]:
    """Classify and resolve all conflicts.

    Returns:
        (0, infos) -- all resolved
        (1, infos) -- non-resolvable conflicts remain
        (2, [])   -- no conflicts exist
    """
    mw = _parent()
    _run_git = mw._run_git
    _print = mw._print

    result = _run_git(["diff", "--name-only", "--diff-filter=U"], cwd=ctx.worktree_path, capture=True)
    if not result.stdout.strip():
        return (2, [])

    conflict_files = result.stdout.strip().splitlines()
    infos = [classify_conflict(f, ctx) for f in conflict_files]

    non_auto = [i for i in infos if not i.auto_resolvable]
    if non_auto:
        for i in non_auto:
            _print(f"  Non-auto-resolvable conflict: {i.path} ({i.classification})")
        return (1, infos)

    # Resolve all
    for info in infos:
        if not resolve_conflict(info, ctx):
            return (1, infos)

    return (0, infos)


def trial_merge(ctx: MergeContext) -> Optional[Tuple[int, list[ConflictInfo]]]:
    """Run a trial merge on a temp branch. Returns (3, infos) if non-auto conflicts, None if clean."""
    mw = _parent()
    _print = mw._print
    _run_git = mw._run_git

    _print("")
    _print("Running trial merge...")
    trial_branch = f"trial/{ctx.args.branch}".replace("//", "/")
    cwd = ctx.worktree_path

    # Create trial branch
    _run_git(["branch", "-D", trial_branch], cwd=cwd, capture=True)
    _run_git(["checkout", "-b", trial_branch], cwd=cwd, capture=True)

    # Attempt merge
    merge_result = _run_git(
        ["merge", f"origin/{ctx.args.target}", "--no-edit"], cwd=cwd, capture=True
    )

    if merge_result.returncode != 0:
        # Check conflicts
        conflicts = _run_git(["diff", "--name-only", "--diff-filter=U"], cwd=cwd, capture=True)
        conflict_files = conflicts.stdout.strip().splitlines() if conflicts.stdout.strip() else []

        if conflict_files:
            infos = [classify_conflict(f, ctx) for f in conflict_files]
            non_auto = [i for i in infos if not i.auto_resolvable]

            if non_auto:
                # Abort trial, restore branch
                _run_git(["merge", "--abort"], cwd=cwd, capture=True)
                _run_git(["checkout", ctx.args.branch], cwd=cwd, capture=True)
                _run_git(["branch", "-D", trial_branch], cwd=cwd, capture=True)

                # Emit structured output
                _print("", err=True)
                _print("\u2554\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2557", err=True)
                _print("\u2551  TRIAL MERGE \u2014 conflicts require agent resolution          \u2551", err=True)
                _print("\u255a\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u255d", err=True)
                _print("", err=True)
                _print(f"Branch:    {ctx.args.branch}", err=True)
                _print(f"Target:    {ctx.args.target}", err=True)
                _print(f"Worktree:  {ctx.worktree_path}", err=True)
                _print("", err=True)
                _print("Conflict analysis:", err=True)
                for info in infos:
                    _print(f"  CONFLICT|{info.path}|{info.classification}", err=True)
                _print("", err=True)
                _print("The real branch is untouched \u2014 no cleanup needed.", err=True)

                return (3, infos)

        # All auto-resolvable or no conflicts -- abort trial
        _run_git(["merge", "--abort"], cwd=cwd, capture=True)

    # Cleanup trial
    _run_git(["checkout", ctx.args.branch], cwd=cwd, capture=True)
    _run_git(["branch", "-D", trial_branch], cwd=cwd, capture=True)

    _print("Trial merge clean \u2014 proceeding with real merge.")
    return None
