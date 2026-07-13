"""Yoke-managed / user-authored file classification.

Canonical Python owner for Yoke-managed file classification.

Holds the authoritative list of Yoke-managed file glob patterns, the
single-file classifier, and the bulk git-status classifier. Callers can
import the module directly or use the CLI entry point:

    python3 -m yoke_core.domain.classify_dirty_files patterns
    python3 -m yoke_core.domain.classify_dirty_files classify-file <path>
    python3 -m yoke_core.domain.classify_dirty_files is-managed-pattern <path>
    python3 -m yoke_core.domain.classify_dirty_files classify-dirty [--repo PATH] [--exclude-worktrees]

Classifications:
    ``yoke-managed`` — safe to auto-commit or discard.
    ``user-authored`` — must be preserved.
"""

from __future__ import annotations

from yoke_core.domain.strategy_docs_paths import STRATEGY_DIR_REL

import argparse
import fnmatch
import subprocess
import sys
from typing import Iterable, Sequence


# Single source of truth for Yoke-managed file glob patterns.
#
# Project-local board and backlog views are untracked/generated. No
# classification is needed for untracked files.
#
# ouroboros/health/* and ouroboros/wrapups/* are now gitignored
# -- no classification needed.
YOKE_MANAGED_PATTERNS: tuple[str, ...] = (
    "ouroboros/simulation-*.md",
    ".agents/skills/yoke/scripts/*",
    ".claude/skills/yoke/scripts/*",
    f"{STRATEGY_DIR_REL}/PAD.md",
)


# ---------------------------------------------------------------------------
# Pattern matching
# ---------------------------------------------------------------------------

def _glob_match(pattern: str, path: str) -> bool:
    """POSIX-shell ``case`` style matching with the same depth semantics.

    The original shell helper relied on ``case "$file" in $pattern)``. This
    matches the entire path against the pattern rather than individual
    segments.
    We re-create that depth tolerance by treating a trailing ``*`` as
    ``*...``.
    """
    if fnmatch.fnmatchcase(path, pattern):
        return True
    # Depth-tolerant trailing wildcard: ".agents/skills/yoke/scripts/*"
    # should match nested helper paths too, because shell case patterns permit
    # nested paths when the dir ends in ``*``.
    if pattern.endswith("/*"):
        prefix = pattern[:-2]
        if path.startswith(prefix + "/"):
            return True
    return False


def is_yoke_managed_pattern(filepath: str) -> bool:
    """Return True when *filepath* matches any Yoke-managed glob."""
    for pattern in YOKE_MANAGED_PATTERNS:
        if _glob_match(pattern, filepath):
            return True
    return False


# ---------------------------------------------------------------------------
# Backlog body-diff refinement
# ---------------------------------------------------------------------------


def _read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read()
    except Exception:
        return ""


def _git_show_head(filepath: str) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["git", "show", f"HEAD:{filepath}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return False, ""
    if result.returncode != 0:
        return False, ""
    return True, result.stdout


def _extract_body_after_frontmatter(content: str) -> str:
    """Return everything after the second ``---`` delimiter."""
    delimiters = 0
    lines_out: list[str] = []
    in_body = False
    for line in content.split("\n"):
        if not in_body:
            if line.strip() == "---":
                delimiters += 1
                if delimiters >= 2:
                    in_body = True
            continue
        lines_out.append(line)
    return "\n".join(lines_out)


def is_yoke_managed_backlog(filepath: str) -> bool:
    """Two-tier body-diff classification for backlog files (historically ``yoke/backlog/*``).

    Returns True when the only change is in the frontmatter (Yoke-managed),
    False when the body differs or the file is untracked (safe default:
    user-authored).
    """
    ok, head_raw = _git_show_head(filepath)
    if not ok:
        return False
    working = _read_text(filepath)
    return _extract_body_after_frontmatter(working) == _extract_body_after_frontmatter(head_raw)


# ---------------------------------------------------------------------------
# Single-file classifier
# ---------------------------------------------------------------------------


def classify_file(filepath: str) -> str:
    """Return ``"yoke-managed"`` or ``"user-authored"`` for *filepath*.

    Backlog files are intentionally absent from
    :data:`YOKE_MANAGED_PATTERNS` (backlog .md views are
    untracked/gitignored generated files) so the shell facade's legacy
    two-tier body-diff refinement for backlog files is a no-op here. The
    ``is_yoke_managed_backlog`` helper is still exposed via the CLI for
    callers that want to inspect tracked backlog files explicitly.
    """
    return (
        "yoke-managed"
        if is_yoke_managed_pattern(filepath)
        else "user-authored"
    )


# ---------------------------------------------------------------------------
# Bulk classification from git status
# ---------------------------------------------------------------------------


def _git_capture(args: Sequence[str], *, repo_path: str | None = None) -> list[str]:
    try:
        result = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=repo_path,
        )
    except Exception:
        return []
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line]


def _exclude_worktree_paths(files: Iterable[str]) -> list[str]:
    filtered: list[str] = []
    for path in files:
        if path.startswith(".worktrees/") or path.startswith(".claude/worktrees/"):
            continue
        filtered.append(path)
    return filtered


def classify_dirty_files(
    *,
    exclude_worktrees: bool = False,
    repo_path: str | None = None,
) -> tuple[list[str], list[str]]:
    """Inspect the git working tree and return ``(yoke_files, user_files)``.

    Considers tracked modifications (``git diff``), staged modifications
    (``git diff --cached``), and untracked files
    (``git ls-files --others --exclude-standard``).
    """
    tracked = _git_capture(["diff", "--name-only"], repo_path=repo_path)
    staged = _git_capture(["diff", "--cached", "--name-only"], repo_path=repo_path)
    untracked = _git_capture(
        ["ls-files", "--others", "--exclude-standard"],
        repo_path=repo_path,
    )

    if exclude_worktrees:
        tracked = _exclude_worktree_paths(tracked)
        staged = _exclude_worktree_paths(staged)
        untracked = _exclude_worktree_paths(untracked)

    combined: list[str] = []
    seen: set[str] = set()
    for bundle in (tracked, staged, untracked):
        for path in bundle:
            if path in seen:
                continue
            seen.add(path)
            combined.append(path)

    # Preserve sorted order to match the shell behaviour.
    combined.sort()

    yoke_files: list[str] = []
    user_files: list[str] = []
    for path in combined:
        if classify_file(path) == "yoke-managed":
            yoke_files.append(path)
        else:
            user_files.append(path)
    return yoke_files, user_files


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _print_patterns() -> int:
    print(" ".join(YOKE_MANAGED_PATTERNS))
    return 0


def _cmd_classify_file(path: str) -> int:
    print(classify_file(path))
    return 0


def _cmd_is_managed_pattern(path: str) -> int:
    return 0 if is_yoke_managed_pattern(path) else 1


def _cmd_is_managed_backlog(path: str) -> int:
    return 0 if is_yoke_managed_backlog(path) else 1


def _cmd_classify_dirty(exclude_worktrees: bool, repo_path: str | None = None) -> int:
    yoke_files, user_files = classify_dirty_files(
        exclude_worktrees=exclude_worktrees,
        repo_path=repo_path,
    )
    # Emit two lines: yoke-managed files (space-separated) and
    # user-authored files (space-separated). Empty lines are fine.
    print(" ".join(yoke_files))
    print(" ".join(user_files))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python3 -m yoke_core.domain.classify_dirty_files"
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("patterns", help="Print YOKE_MANAGED_PATTERNS")

    p_classify = sub.add_parser("classify-file", help="Classify a single path")
    p_classify.add_argument("path")

    p_pattern = sub.add_parser(
        "is-managed-pattern", help="Exit 0 when path matches a managed pattern"
    )
    p_pattern.add_argument("path")

    p_backlog = sub.add_parser(
        "is-managed-backlog",
        help="Exit 0 when backlog file has frontmatter-only changes vs HEAD",
    )
    p_backlog.add_argument("path")

    p_dirty = sub.add_parser(
        "classify-dirty", help="Bulk classify git dirty files (stdout: two lines)"
    )
    p_dirty.add_argument("--repo")
    p_dirty.add_argument("--exclude-worktrees", action="store_true")

    args = parser.parse_args(argv)

    if args.command == "patterns":
        return _print_patterns()
    if args.command == "classify-file":
        return _cmd_classify_file(args.path)
    if args.command == "is-managed-pattern":
        return _cmd_is_managed_pattern(args.path)
    if args.command == "is-managed-backlog":
        return _cmd_is_managed_backlog(args.path)
    if args.command == "classify-dirty":
        return _cmd_classify_dirty(args.exclude_worktrees, args.repo)
    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
