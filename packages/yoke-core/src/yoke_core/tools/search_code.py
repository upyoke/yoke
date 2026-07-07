"""Worktree-aware recursive code-search helper.

Resolves the bound worktree (or main repo root) for a backlog item and runs
a recursive search against safe defaults so agents do not need to author
broad relative ``grep -r`` shapes that are correctly suspicious under
worktree/static-cwd guardrails.

CLI shape::

    python3 -m yoke_core.tools.search_code \
        --item YOK-N --pattern PATTERN --scope worktree|main

Engine selection: ``rg`` is preferred when present; a tested Python fallback
runs otherwise. Output mirrors ``rg --line-number --no-heading`` shape:
``<path>:<line>:<match>`` with paths relative to the search root. When a
single item resolves to multiple worktrees (epic), each match is prefixed
with the worktree root so callers can disambiguate.

Exit codes::

    0  matches found
    1  ran cleanly, no matches found
    2  invalid input (bad item id, lookup failure, invalid scope)
    3  --scope worktree requested but no worktree directory is bound
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple

from yoke_core.domain.worktree_item_resolve import (
    ResolvedWorktree,
    resolve_item_worktree,
)


DEFAULT_EXCLUDES: Tuple[str, ...] = (
    ".git",
    ".worktrees",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
)

EXIT_OK = 0
EXIT_NO_MATCH = 1
EXIT_BAD_INPUT = 2
EXIT_NO_WORKTREE = 3


class SearchError(Exception):
    """Raised when the selected search engine cannot run the pattern."""


def _build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m yoke_core.tools.search_code",
        description=(
            "Recursive worktree-aware code search. Resolves the bound "
            "worktree (or main repo root) for a backlog item via the "
            "canonical Yoke resolvers and runs rg / a Python fallback "
            "with safe excludes."
        ),
    )
    parser.add_argument(
        "--item",
        required=True,
        help="Backlog item ID (e.g. YOK-N).",
    )
    parser.add_argument(
        "--pattern",
        required=True,
        help="Regex pattern (rg / Python re syntax).",
    )
    parser.add_argument(
        "--scope",
        choices=("worktree", "main"),
        default="worktree",
        help=(
            "'worktree' searches the bound worktree(s) for the item; "
            "'main' searches the project repo root only when explicit. "
            "Default: worktree."
        ),
    )
    parser.add_argument(
        "--engine",
        choices=("auto", "rg", "python"),
        default="auto",
        help=(
            "Search engine. 'auto' uses rg when present and falls back to "
            "the Python implementation when absent. 'rg' / 'python' force "
            "the engine for testing and reproducibility."
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_argparser().parse_args(argv)

    try:
        resolved = resolve_item_worktree(args.item)
    except (ValueError, LookupError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_BAD_INPUT

    if args.scope == "worktree":
        existing, missing = _split_worktrees(resolved)
        if not existing:
            _emit_no_worktree_remediation(args.item)
            return EXIT_NO_WORKTREE
        if missing:
            print(
                f"WARNING: {len(missing)} declared worktree(s) not found "
                "on disk; searching only the existing worktree(s).",
                file=sys.stderr,
            )
            for path in missing:
                print(f"  missing: {path}", file=sys.stderr)
        roots = existing
        # Prefix every match when the resolver declared more than one
        # worktree, even if only one currently exists. The worktree root in
        # the prefix keeps multi-worktree output unambiguous.
        multi = len(resolved.paths) > 1
    else:
        roots = (resolved.repo,)
        multi = False

    engine = _select_engine(args.engine)
    matched = False
    try:
        for root in roots:
            for line in _search_root(root, args.pattern, engine):
                print(f"{root}::{line}" if multi else line)
                matched = True
    except SearchError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_BAD_INPUT
    return EXIT_OK if matched else EXIT_NO_MATCH


def _split_worktrees(
    resolved: ResolvedWorktree,
) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
    """Split the resolver's declared worktrees into ``(existing, missing)``.

    Existing entries have a real on-disk directory; missing entries were
    declared by the resolver (epic task rows, primary issue path) but no
    worktree directory exists at the path yet.
    """
    declared = tuple(p for p in resolved.paths if p)
    existing = tuple(p for p in declared if Path(p).is_dir())
    missing = tuple(p for p in declared if not Path(p).is_dir())
    return existing, missing


def _emit_no_worktree_remediation(item_ref: str) -> None:
    msg = (
        f"ERROR: no worktree directory exists for {item_ref}. "
        "search_code --scope worktree requires a bound worktree.\n"
        "Remediation:\n"
        f"  python3 -m yoke_core.domain.worktree_preflight --item {item_ref}\n"
        f"  /yoke advance {item_ref} implementation\n"
        "Or rerun with --scope main to search the project repo root."
    )
    print(msg, file=sys.stderr)


def _select_engine(requested: str) -> str:
    """Pick ``rg`` or ``python`` based on availability and the user request."""
    if requested == "python":
        return "python"
    if requested == "rg":
        return "rg" if shutil.which("rg") else "python"
    # auto
    return "rg" if shutil.which("rg") else "python"


def _search_root(root: str, pattern: str, engine: str) -> Iterable[str]:
    if engine == "rg":
        yield from _search_root_rg(root, pattern)
    else:
        yield from _search_root_python(root, pattern)


def _search_root_rg(root: str, pattern: str) -> Iterable[str]:
    """Run ``rg --line-number --no-heading`` from *root* with safe excludes."""
    cmd: List[str] = [
        "rg",
        "--line-number",
        "--no-heading",
        "--color",
        "never",
    ]
    for excl in DEFAULT_EXCLUDES:
        cmd.extend(["--glob", f"!{excl}"])
        cmd.extend(["--glob", f"!**/{excl}/**"])
    cmd.extend(["--", pattern, "."])
    proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True)
    # rg exits 1 on no-match, 2 on real errors. Treat 0/1 as clean output;
    # surface stderr for >1 so the caller can react.
    if proc.returncode > 1:
        detail = proc.stderr.strip() or "rg search failed"
        raise SearchError(detail)
    for line in proc.stdout.splitlines():
        if line:
            yield line


def _search_root_python(root: str, pattern: str) -> Iterable[str]:
    """Walk *root* with ``DEFAULT_EXCLUDES`` pruned and emit ``rg``-shape rows.

    Produces ``<rel>:<line>:<content>`` rows where ``<rel>`` is relative to
    *root*. Binary files (any chunk containing a NUL byte) are skipped to
    mirror ``rg``'s default filter; OS errors (permission denied, broken
    symlinks) are skipped silently rather than aborting the walk.
    """
    try:
        rgx = re.compile(pattern)
    except re.error as exc:
        raise SearchError(f"invalid regex: {exc}") from exc
    root_path = Path(root)
    for dirpath, dirnames, filenames in os.walk(root_path):
        dirnames[:] = [d for d in dirnames if d not in DEFAULT_EXCLUDES]
        dirnames.sort()
        for fname in sorted(filenames):
            fpath = Path(dirpath) / fname
            try:
                if _looks_binary(fpath):
                    continue
                text = fpath.read_text(encoding="utf-8", errors="strict")
            except (OSError, UnicodeDecodeError):
                continue
            for lineno, line in enumerate(text.splitlines(), 1):
                if rgx.search(line):
                    rel = fpath.relative_to(root_path)
                    yield f"{rel}:{lineno}:{line}"


def _looks_binary(path: Path) -> bool:
    """Cheap binary-file probe: true when the head chunk contains a NUL byte."""
    try:
        with path.open("rb") as fh:
            chunk = fh.read(8192)
    except OSError:
        return True
    return b"\x00" in chunk


if __name__ == "__main__":
    raise SystemExit(main())
