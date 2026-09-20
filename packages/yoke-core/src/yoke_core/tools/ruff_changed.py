"""Lint changed Python files from the active claimed source checkout.

The checkout is never taken from the ambient working directory. A
harness re-applies a previous ``cd`` between tool calls, so a
cwd-derived tree can silently be a different checkout than the one
the caller means — and a branch diff taken against the wrong tree is
empty, which this command would otherwise report as a clean pass.
The tree comes from an explicit ``--workdir`` or from the session's
claimed lane, and every line it prints names the tree it used.

The file set is the shared working-tree changed-path scope, so an
authored-but-not-yet-added file is linted here exactly as the required
CI contract will lint it once committed. Every result names that scope's
composition, so a green can be read for what it actually covered.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from yoke_contracts.project_contract.changed_path_scope import (
    ChangedPathError,
    WorkingTreeChangedPaths,
    tracked_changed_paths,
    untracked_paths,
)
from yoke_core.tools import source_dev_run


@dataclass(frozen=True)
class ChangedPythonSelection:
    """Python paths and the exact Git revisions used to select them."""

    paths: tuple[str, ...]
    base_sha: str
    head_sha: str
    scope: WorkingTreeChangedPaths


def _git_output(root: Path, arguments: Sequence[str]) -> bytes:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode:
        detail = os.fsdecode(completed.stderr).strip()
        raise ChangedPathError(completed.returncode, detail)
    return completed.stdout


def _existing_python(root: Path, paths: Sequence[str]) -> tuple[str, ...]:
    """Keep the Python files Ruff can actually open, in the order given."""
    return tuple(
        relative
        for relative in paths
        if (root / relative).suffix == ".py" and (root / relative).is_file()
    )


def select_changed_python_paths(base: str, root: Path) -> ChangedPythonSelection:
    """Select every Python change a commit of this tree would carry from ``base``.

    That is committed, staged, and unstaged tracked edits plus the untracked
    files Git would add — the same set the required CI contract derives for
    this work once it is committed.
    """
    head_sha = os.fsdecode(_git_output(root, ("rev-parse", "--verify", "HEAD"))).strip()
    base_sha = os.fsdecode(_git_output(root, ("merge-base", base, head_sha))).strip()
    scope = WorkingTreeChangedPaths(
        tracked=_existing_python(root, tracked_changed_paths(root, base_sha)),
        untracked=_existing_python(root, untracked_paths(root)),
    )
    return ChangedPythonSelection(scope.paths, base_sha, head_sha, scope)


def changed_python_paths(base: str, root: Path) -> tuple[str, ...]:
    """Return existing changed Python paths, preserving unusual filenames."""
    return select_changed_python_paths(base, root).paths


def _run_ruff(root: Path, arguments: Sequence[str], paths: Sequence[str]) -> int:
    completed = subprocess.run(
        ["uv", "run", "--frozen", "ruff", *arguments, "--", *paths],
        cwd=root,
        check=False,
    )
    return completed.returncode


def resolve_tree(workdir: str | None) -> tuple[Path | None, str | None]:
    """Return the checkout to lint, or the reason none could be named.

    ``workdir`` wins when given. Otherwise the tree is the session's
    claimed source lane — never the working directory, which a harness
    may have re-applied from an earlier call.
    """
    if workdir:
        tree = Path(workdir).expanduser().resolve()
        if not (tree / ".git").exists():
            return None, f"--workdir is not a Git checkout: {tree}"
        return tree, None
    return source_dev_run.claimed_lane_root()


def run(base: str, *, format_check: bool = False, root: Path) -> int:
    checkout = Path(root).resolve()
    try:
        selection = select_changed_python_paths(base, checkout)
    except ChangedPathError as exc:
        print(
            f"ruff-changed: could not compare {base!r} with HEAD",
            file=sys.stderr,
        )
        if str(exc):
            print(str(exc), file=sys.stderr)
        return exc.returncode or 1

    paths = selection.paths
    count = len(paths)
    coverage = selection.scope.coverage_sentence(noun="Python file")
    if not paths:
        print(
            "ruff-changed: no changed Python files after comparing "
            f"base SHA {selection.base_sha}, HEAD {selection.head_sha}, and the "
            f"working tree in {checkout}; passing"
        )
        print(f"ruff-changed: {coverage}")
        return 0

    noun = "file" if count == 1 else "files"
    print(
        f"ruff-changed: checking {count} changed Python {noun} against "
        f"{base} in {checkout}"
    )
    print(f"ruff-changed: {coverage}")
    check_status = _run_ruff(checkout, ("check",), paths)
    if check_status:
        print(
            f"ruff-changed: ruff check failed with status {check_status}",
            file=sys.stderr,
        )
        return check_status

    if format_check:
        format_status = _run_ruff(checkout, ("format", "--check"), paths)
        if format_status:
            print(
                f"ruff-changed: ruff format --check failed with status {format_status}",
                file=sys.stderr,
            )
            return format_status

    suffix = " and format" if format_check else ""
    print(f"ruff-changed: check{suffix} passed for {count} {noun} in {checkout}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke dev ruff-changed",
        description=(
            "Run Ruff on every existing Python change a commit of the tree "
            "would carry (committed, staged, unstaged, and untracked) in an "
            "explicitly named Yoke source checkout, defaulting to the "
            "current session's claimed lane."
        ),
    )
    parser.add_argument(
        "--base",
        required=True,
        metavar="REF",
        help=(
            "Compare the merge-base of REF and HEAD with the working tree: "
            "staged, unstaged, and untracked non-ignored changes."
        ),
    )
    parser.add_argument(
        "--workdir",
        metavar="PATH",
        help=(
            "Checkout to lint. Defaults to this session's claimed source "
            "lane; the working directory is never used."
        ),
    )
    parser.add_argument(
        "--format-check",
        action="store_true",
        help="Also run `ruff format --check` on the changed files.",
    )
    parsed = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    tree, error = resolve_tree(parsed.workdir)
    if tree is None:
        print(
            "ruff-changed: refusing to guess which checkout to lint",
            file=sys.stderr,
        )
        print(f"  reason: {error}", file=sys.stderr)
        print(
            f"  working directory (not used): {Path.cwd()}",
            file=sys.stderr,
        )
        print(
            "  name the checkout: yoke dev ruff-changed --base "
            f"{parsed.base} --workdir <checkout>",
            file=sys.stderr,
        )
        return 1
    return run(parsed.base, format_check=parsed.format_check, root=tree)


__all__ = [
    "ChangedPathError",
    "ChangedPythonSelection",
    "changed_python_paths",
    "main",
    "resolve_tree",
    "run",
    "select_changed_python_paths",
]


if __name__ == "__main__":  # pragma: no cover - module adapter
    raise SystemExit(main())
