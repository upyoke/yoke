"""Destructive-git classification shared by the engine and client guards.

The engine guard (``yoke_core.domain.lint_destructive_git``) and the
client-local guard (``yoke_harness.hooks.local_policies``) both decide a
command's destructive shape and the local state it threatens here, so the
two cannot drift. Callers pass their own ``run_git(worktree, *args)``
runner; it returns a ``CompletedProcess`` or ``None`` when git could not run.

A path-scoped restore or checkout threatens only the modified paths its
pathspec covers. Unmerged paths are not threatened while a rebase, merge,
cherry-pick or revert is in progress: their content comes from the
commits being combined, so resolving one conflicted file is not a wipe.
"""

from __future__ import annotations

import os
import subprocess
from typing import Callable, Optional

GitRunner = Callable[..., Optional[subprocess.CompletedProcess]]

# Porcelain XY codes git uses for unmerged index entries.
UNMERGED_CODES = frozenset({"DD", "AU", "UD", "UA", "DU", "AA", "UU"})
# Git-dir entries present while a conflict-producing operation is in progress.
CONFLICT_OPERATION_PATHS = (
    "rebase-merge",
    "rebase-apply",
    "MERGE_HEAD",
    "CHERRY_PICK_HEAD",
    "REVERT_HEAD",
)
PATH_SHAPES = ("checkout_path_discard", "restore_worktree_path")
STASH_SHAPES = ("stash_drop", "stash_clear")


def pathspec_like(token: str, worktree: str = "") -> bool:
    """True when a checkout arg names a working-tree path rather than a ref."""
    if token in (".", "..") or token.startswith(("./", "../")) or token.endswith("/"):
        return True
    return os.path.exists(os.path.join(worktree, token) if worktree else token)


def classify_shape(args: list[str], worktree: str = "") -> Optional[str]:
    """Return the destructive shape for a git argv, or ``None``."""
    if not args:
        return None
    verb, rest = args[0], args[1:]
    if verb == "reset":
        return "reset_hard" if "--hard" in rest else None
    if verb == "clean":
        for a in rest:
            if a == "--force":
                return "clean_force"
            if (
                a.startswith("-")
                and not a.startswith("--")
                and "n" not in a[1:]
                and "f" in a[1:]
            ):
                return "clean_force"
        return None
    if verb == "stash":
        return f"stash_{rest[0]}" if rest and rest[0] in ("drop", "clear") else None
    if verb == "checkout":
        if "--" in rest:
            return "checkout_path_discard"
        if any(a in ("-f", "--force") for a in rest):
            return "checkout_force_branch"
        if any(pathspec_like(a, worktree) for a in rest if not a.startswith("-")):
            return "checkout_path_discard"
        return None
    if verb == "worktree" and rest and rest[0] == "remove":
        return "worktree_remove"
    if verb == "restore":
        has_wt = "--worktree" in rest or "-W" in rest
        has_st = "--staged" in rest or "-S" in rest
        if has_st and not has_wt:
            return None
        if any(not a.startswith("-") for a in rest) or has_wt:
            return "restore_worktree_path"
    return None


def path_args(args: list[str]) -> list[str]:
    """Return the pathspec operands of a checkout/restore argv."""
    rest = args[1:]
    if "--" in rest:
        return rest[rest.index("--") + 1 :]
    paths, skip = [], False
    for a in rest:
        if skip:
            skip = False
        # `-s`/`--source` consume a value; `-S` is `--staged` and does not.
        elif a in ("--source", "-s"):
            skip = True
        elif not a.startswith("-"):
            paths.append(a)
    return paths


def pathspec_covers(pathspec: str, rel: str) -> bool:
    norm = pathspec.rstrip("/")
    while norm.startswith("./"):
        norm = norm[2:]
    if norm in (".", ""):
        return True
    return rel == norm or rel.startswith(norm + "/")


def conflict_operation_in_progress(worktree: str, run_git: GitRunner) -> bool:
    """True while the worktree is mid-rebase, -merge, -cherry-pick or -revert."""
    probe: list[str] = []
    for name in CONFLICT_OPERATION_PATHS:
        probe += ["--git-path", name]
    result = run_git(worktree, "rev-parse", *probe)
    if not result or result.returncode != 0:
        return False
    return any(
        os.path.exists(os.path.join(worktree, line.strip()))
        for line in result.stdout.splitlines()
        if line.strip()
    )


def worktree_status(
    worktree: str, run_git: GitRunner
) -> Optional[tuple[list[str], list[str]]]:
    """Return ``(modified, untracked)`` paths, or ``None`` when unreadable.

    Unmerged paths drop out of ``modified`` during a conflict operation.
    """
    result = run_git(worktree, "status", "--porcelain", "--untracked-files=all")
    if not result or result.returncode != 0:
        return None
    modified: list[str] = []
    unmerged: list[str] = []
    untracked: list[str] = []
    for line in result.stdout.splitlines():
        if len(line) < 4:
            continue
        code, path = line[:2], line[3:]
        if code == "??":
            untracked.append(path)
        elif code in UNMERGED_CODES:
            unmerged.append(path)
        else:
            modified.append(path.split(" -> ")[-1])
    if unmerged and not conflict_operation_in_progress(worktree, run_git):
        modified.extend(unmerged)
    return modified, untracked


def stash_drop_selectors(args: list[str]) -> tuple[list[str] | None, bool]:
    """Return ``(named selectors, unresolved)`` for a ``stash drop`` argv.

    Git's default drop target is ``stash@{0}``. A selector that still
    contains ``$`` could not be resolved; the caller must treat that as
    the whole stash set rather than as nothing. A ``#`` token is a shell
    comment, not a stash ref — the audit-only suppression token lives
    there and must not be read as the target.
    """
    rest = args[2:] if len(args) >= 2 else []
    named: list[str] = []
    for token in rest:
        if token.startswith("-"):
            continue
        if token.startswith("#"):
            break
        named.append(token)
        break
    if not named:
        return ["stash@{0}"], False
    if any("$" in token for token in named):
        return None, True
    return named, False


def stash_refs_from_list(stdout: str) -> list[str]:
    """Parse ``git stash list`` into ``stash@{N}`` refs."""
    refs: list[str] = []
    for line in stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        refs.append(stripped.split(":", 1)[0].strip())
    return refs


def stash_threatened_refs(
    shape: str,
    args: list[str],
    stash_list: Optional[str],
) -> Optional[list[str]]:
    """Name the stash refs a drop/clear would discard, or fail closed."""
    if shape not in STASH_SHAPES:
        return None
    refs = stash_refs_from_list(stash_list or "")
    if shape == "stash_clear":
        return refs or None
    selectors, unresolved = stash_drop_selectors(args)
    if unresolved:
        return refs or ["all stashes (selector could not be resolved)"]
    if not refs or selectors is None:
        return None
    threatened = [selector for selector in selectors if selector in refs]
    return threatened or None


def _clean_threats(worktree: str, args: list[str], run_git: GitRunner) -> list[str]:
    dry_args = [
        "--dry-run"
        if a == "--force"
        else ("-" + a[1:].replace("f", "n"))
        if a.startswith("-") and not a.startswith("--") and "f" in a[1:]
        else a
        for a in args[1:]
    ]
    result = run_git(worktree, "clean", *dry_args)
    if not result or result.returncode != 0:
        return []
    prefix = "Would remove "
    return [
        line.removeprefix(prefix).rstrip()
        for line in result.stdout.splitlines()
        if line.startswith(prefix)
    ]


def threatened_state(
    shape: str, worktree: str, args: list[str], run_git: GitRunner
) -> Optional[list[str]]:
    """Name the local state *shape* would discard, or ``None`` when safe.

    ``worktree_remove`` needs claim state and is judged by the engine only.
    """
    inside = run_git(worktree, "rev-parse", "--is-inside-work-tree")
    if not inside or inside.returncode != 0:
        return None
    if shape in STASH_SHAPES:
        listing = run_git(worktree, "stash", "list")
        return stash_threatened_refs(
            shape,
            args,
            listing.stdout if listing and listing.returncode == 0 else None,
        )
    if shape == "clean_force":
        return _clean_threats(worktree, args, run_git) or None
    if shape not in ("reset_hard", "checkout_force_branch", *PATH_SHAPES):
        return None
    status = worktree_status(worktree, run_git)
    modified = status[0] if status else []
    if shape in PATH_SHAPES and (paths := path_args(args)):
        modified = [m for m in modified if any(pathspec_covers(p, m) for p in paths)]
    return modified or None


__all__ = [
    "CONFLICT_OPERATION_PATHS",
    "GitRunner",
    "UNMERGED_CODES",
    "classify_shape",
    "conflict_operation_in_progress",
    "path_args",
    "pathspec_covers",
    "pathspec_like",
    "stash_drop_selectors",
    "stash_refs_from_list",
    "stash_threatened_refs",
    "threatened_state",
    "worktree_status",
]
