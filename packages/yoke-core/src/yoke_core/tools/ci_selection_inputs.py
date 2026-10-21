"""What a CI selection dispatch names, read the same way by plan and run.

The selection workflow's plan job and every shard receive the same dispatch
inputs: the commit under test, the merge base, and the bare pytest arguments.
Both refuse a checkout of any other commit, compute the impacted selection
with the same code, and read the dispatched positional targets the same way,
so the plan sizes exactly the work the shards collect.
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path
from typing import Sequence

from yoke_core.tools._watch_pytest_args import (
    format_would_widen_advisory,
    pytest_flag_consumes_value,
)

#: The dispatch and the checkout disagree, or there is nothing to run.
#: Either is a usage defect of the workflow, not a test verdict.
EXIT_USAGE = 2


def head_sha(root: Path) -> str:
    """The commit *root* has checked out, or empty when git cannot say."""
    completed = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.stdout.strip() if completed.returncode == 0 else ""


def checkout_mismatch(root: Path, expected_head_sha: str) -> str:
    """Why *root* is the wrong tree for this dispatch; empty when it is right."""
    if not expected_head_sha:
        return ""
    actual = head_sha(root)
    if actual == expected_head_sha:
        return ""
    return (
        f"Error: ci_selection_run checked out {actual[:12] or 'no commit'} "
        f"but the dispatch named {expected_head_sha[:12]}; the workflow "
        "must check out inputs.head_sha before running the selection"
    )


def selection_paths(root: Path, base_sha: str) -> list[str] | None:
    """Test paths reachable from ``base_sha...HEAD``, or None when none are.

    Bounded, exactly as the wrapper runs it locally: an unbounded change
    runs the computable subset here and prints the same advisory, because
    the project's full suite is the gate's job, not the selection's.
    """
    from yoke_core.tools.watch_pytest_project_python import impacted_selection

    selection = impacted_selection(base_sha, bounded=True, root=root)
    if selection is None:
        return None
    if selection.bounded_deferral:
        print(
            format_would_widen_advisory(
                rule=selection.fallback_rule,
                trigger_paths=selection.trigger_paths,
            ),
            flush=True,
        )
    return list(selection.pytest_paths())


def split_args(args: Sequence[str]) -> tuple[list[str], list[str]]:
    """``(targets, options)``: what *args* collects, and everything else."""
    targets: list[str] = []
    options: list[str] = []
    skip_next = False
    for token in args:
        if skip_next:
            skip_next = False
            options.append(token)
            continue
        if token.startswith("-"):
            skip_next = pytest_flag_consumes_value(token)
            options.append(token)
            continue
        targets.append(token)
    return targets, options


def positional_args(args: Sequence[str]) -> list[str]:
    """The collection targets *args* names of its own."""
    return split_args(args)[0]


def has_positional_args(args: Sequence[str]) -> bool:
    """Whether *args* name any collection target of their own."""
    return bool(positional_args(args))


def add_dispatch_arguments(parser: argparse.ArgumentParser) -> None:
    """Declare the dispatch values the plan and the run both read.

    The workflow passes every value attached (``--pytest-args=-q``): a
    dispatched pytest argument is itself dash-prefixed, and argparse reads a
    lone ``-q`` in the following token as another option rather than as this
    option's value.
    """
    parser.add_argument(
        "--base-sha",
        default="",
        help="Merge base the selection is computed against; empty uses "
        "--pytest-args as given.",
    )
    parser.add_argument(
        "--head-sha",
        default="",
        help="Commit the dispatch named; any other checkout is refused.",
    )
    parser.add_argument(
        "--pytest-args",
        default="",
        help="Shell-quoted bare pytest arguments appended to the selection; "
        "pass the value attached (--pytest-args=-q) so a dash-prefixed "
        "argument is not read as another option.",
    )
    parser.add_argument(
        "--root",
        default=None,
        help="Checkout to run in (default: the working directory).",
    )


__all__ = [
    "EXIT_USAGE",
    "add_dispatch_arguments",
    "checkout_mismatch",
    "has_positional_args",
    "head_sha",
    "positional_args",
    "selection_paths",
    "split_args",
]
