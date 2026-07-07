"""Product-safe ``yoke git pre-commit`` hook body."""

from __future__ import annotations

import pathlib
import subprocess
import sys
from typing import Iterable

from yoke_harness.git_hooks import file_line_check


def _git_name_only(args: Iterable[str]) -> list[str]:
    try:
        result = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return []
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line]


def find_diverged(diverged: Iterable[str], staged: Iterable[str]) -> list[str]:
    """Return staged paths that also have unstaged working-tree changes."""
    staged_set = set(staged)
    return [path for path in diverged if path in staged_set]


def _format_warning(files: list[str]) -> str:
    lines = [
        "WARNING: These staged files have unstaged changes; commit may not "
        "match working tree:",
    ]
    lines.extend(f"  {path}" for path in files)
    lines.append(
        "\nRun 'git add <file>' to stage latest content, "
        "or 'git commit --no-verify' to skip this check."
    )
    return "\n".join(lines) + "\n"


def _emit_diverged_warning() -> None:
    diverged = _git_name_only(["diff", "--name-only"])
    if not diverged:
        return
    staged = _git_name_only(["diff", "--cached", "--name-only"])
    if not staged:
        return
    warn_files = find_diverged(diverged, staged)
    if warn_files:
        sys.stderr.write(_format_warning(warn_files))


def _resolve_repo_root() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    root = result.stdout.strip()
    return root or None


def _format_file_line_summary(
    verdict: file_line_check.CheckVerdict, *, limit: int
) -> str:
    lines = [
        "ERROR: file-line-limit gate blocked this commit.",
        "",
        "Hard fails:",
    ]
    for change in verdict.hard_fails:
        if change.old_line_count == 0:
            detail = (
                f"NEW authored file is {change.new_line_count} lines "
                f"(limit: {limit})"
            )
        elif change.old_line_count > limit:
            detail = (
                f"existing {change.old_line_count}-line authored file grew "
                f"to {change.new_line_count} lines"
            )
        else:
            detail = (
                f"authored file grew from {change.old_line_count} to "
                f"{change.new_line_count} lines (crosses {limit}-line limit)"
            )
        lines.append(f"  - {change.path}: {detail}")
    lines.append("")
    lines.append("Run `yoke check file-line --staged` to re-inspect.")
    lines.append(
        "Split the file into smaller modules, or use "
        "`git commit --no-verify` to bypass."
    )
    return "\n".join(lines) + "\n"


def _run_file_line_check_or_block() -> int:
    repo_root = _resolve_repo_root()
    if repo_root is None:
        return 0
    verdict = file_line_check.changed_files_check(
        repo_root=pathlib.Path(repo_root),
        staged=True,
    )
    policy = file_line_check.resolved_policy(pathlib.Path(repo_root))
    if verdict.ok:
        return 0
    if not verdict.hard_fails:
        sys.stderr.write(
            "ERROR: file-line-limit gate could not inspect staged files: "
            f"{verdict.summary}\n"
            "Use `git commit --no-verify` to bypass this check.\n"
        )
        return 1
    sys.stderr.write(
        _format_file_line_summary(verdict, limit=policy.limit)
    )
    return 1


def run() -> int:
    """Run the product-safe local pre-commit checks."""
    _emit_diverged_warning()
    return _run_file_line_check_or_block()


def main() -> int:
    return run()


__all__ = [
    "find_diverged",
    "main",
    "run",
]
