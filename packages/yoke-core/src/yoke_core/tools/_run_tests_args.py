"""Argument parsing for the generic test runner.

Split from :mod:`yoke_core.tools.run_tests` to keep that module under the
authored-file line cap; the runner owns the behavior, this module only
owns how the command line names it.
"""

from __future__ import annotations

import argparse
from typing import List, Sequence

from yoke_core.domain import verification_tree_binding
from yoke_core.tools.pytest_remote_selection import LOCAL_ENV, LOCAL_FLAG

DEFAULT_TESTPATHS: tuple[str, ...] = ("runtime/api", "runtime/harness", "tests")


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="yoke-run-tests",
        description=(
            "Run Yoke's Python test suite. For a project that declares its "
            "CI workflow the run executes on CI by default; "
            f"{LOCAL_FLAG} runs it on this machine under the worker budget."
        ),
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help=(
            "Optional test paths (defaults to "
            f"{' '.join(DEFAULT_TESTPATHS)})."
        ),
    )
    parser.add_argument(
        "-k",
        "--keyword",
        default=None,
        help="pytest -k expression to filter tests by substring/keyword.",
    )
    parser.add_argument(
        "--fail-fast",
        "-x",
        action="store_true",
        help="Stop at first failing test (pytest -x).",
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Minimal output (pytest -q).",
    )
    parser.add_argument(
        "--list",
        dest="list_only",
        action="store_true",
        help="Collect and list test node IDs without running (pytest --collect-only).",
    )
    parser.add_argument(
        "--no-parallel",
        dest="no_parallel",
        action="store_true",
        help=(
            "Disable pytest-xdist parallel execution (default is "
            "``-n auto``). Use to debug order-sensitive failures."
        ),
    )
    parser.add_argument(
        LOCAL_FLAG,
        dest="local",
        action="store_true",
        help=(
            "Run on this machine instead of the project's CI: order-sensitive "
            "debugging, a tree you want to try before committing, or an "
            f"unreachable CI. {LOCAL_ENV}=1 does the same for a whole shell."
        ),
    )
    parser.add_argument(
        verification_tree_binding.ALLOW_TREE_MISMATCH_FLAG,
        dest="allow_tree_mismatch",
        action="store_true",
        help=(
            "Run even when the resolved repo root is outside the session's "
            "claimed worktree. For a deliberate cross-tree run; the runner "
            "names both trees so the result is attributable."
        ),
    )
    parser.add_argument(
        "--",
        dest="passthrough_separator",
        nargs=argparse.REMAINDER,
        help=argparse.SUPPRESS,
    )
    return parser.parse_args(list(argv))


def split_passthrough(raw: Sequence[str]) -> tuple[List[str], List[str]]:
    """Return ``(runner args, pytest pass-through)`` split on ``--``."""
    args = list(raw)
    if "--" in args:
        index = args.index("--")
        return args[:index], args[index + 1 :]
    return args, []


__all__ = ["DEFAULT_TESTPATHS", "parse_args", "split_passthrough"]
