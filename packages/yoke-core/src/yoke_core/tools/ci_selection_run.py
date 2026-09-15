"""Run one change-scoped pytest selection on a CI runner.

The remote half of ``yoke watch pytest``. The wrapper on the developer's
machine pushes the lane commit and dispatches the project's selection
workflow with the commit under test, the merge base the change is measured
against, and the bare pytest arguments it was given. The workflow checks
that commit out and runs this module, which does on the runner exactly what
the wrapper would have done locally: compute the impacted selection from
``(base_sha, head_sha)`` with the same selection code, print the same
``impacted-selection`` telemetry line, and run pytest. Local and remote
captures therefore read alike, and the test list is a function of the two
commits rather than of whichever working tree happened to be present.

A selection large enough to be worth it is cut across several runners: the
workflow's plan job asks this module how many shards the selection earns,
fans its matrix out that wide, and hands each job the same split count and
its own group, so the matrix and the split are one number and every selected
test runs in exactly one group.

Output is mirrored into the file the workflow uploads as an artifact,
written as the run proceeds so a job killed mid-run still uploads what it
reached.
"""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Sequence

from yoke_core.tools._pytest_parallel import has_explicit_workers
from yoke_core.tools._watch_pytest_args import (
    NO_SELECTED_TESTS,
    format_would_widen_advisory,
    pytest_flag_consumes_value,
)
from yoke_core.tools.ci_shards import DURATIONS_PATH, OUTPUT_LOG, shard_number

#: Every core of the runner, flat: the RAM-aware cliff the local runners
#: apply protects a shared workstation, which a hosted runner is not.
CI_WORKERS = "auto"

#: The dispatch and the checkout disagree, or there is nothing to run.
#: Either is a usage defect of the workflow, not a test verdict.
EXIT_USAGE = 2

#: pytest's status when its collection left nothing to run. For one shard of
#: several that can mean the split emptied this group rather than the
#: selection finding nothing, which the log's deselected count settles.
EXIT_NO_TESTS_COLLECTED = 5


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


def pytest_command(
    paths: Sequence[str],
    passthrough: Sequence[str],
    *,
    splits: int = 1,
    group: int = 1,
) -> list[str]:
    """The pytest invocation for *paths* plus the caller's own arguments.

    One shard of several adds the split the plan sized, through the same
    duration-balanced machinery and committed profile the full suite splits
    with: the selection each group collects is identical, so every selected
    test is assigned to exactly one of them.
    """
    argv = [sys.executable, "-m", "pytest", *paths, *passthrough]
    if not has_explicit_workers(passthrough):
        argv.extend(["-n", CI_WORKERS])
    if splits > 1:
        argv.extend([
            "--splits", str(splits),
            "--group", str(group),
            "--splitting-algorithm", "least_duration",
            "--durations-path", DURATIONS_PATH,
        ])
    return argv


def positional_args(args: Sequence[str]) -> list[str]:
    """The collection targets *args* names of its own."""
    targets: list[str] = []
    skip_next = False
    for token in args:
        if skip_next:
            skip_next = False
            continue
        if token.startswith("-"):
            skip_next = pytest_flag_consumes_value(token)
            continue
        targets.append(token)
    return targets


def has_positional_args(args: Sequence[str]) -> bool:
    """Whether *args* name any collection target of their own."""
    return bool(positional_args(args))


def collects_anything(
    root: Path, paths: Sequence[str], passthrough: Sequence[str]
) -> bool:
    """Whether the unsplit selection collects a test at all in *root*.

    Asked only when a run reported none: pytest answers it in its exit
    status, which separates a group the split left empty (the selection
    collects, the other groups carry it) from a selection that matches
    nothing here (every group reports the same, and it is a real failure).
    """
    command = [
        sys.executable, "-m", "pytest", *paths, *passthrough,
        "--collect-only", "-q", "-n", "0",
    ]
    print(f"$ {shlex.join(command)}", flush=True)
    return subprocess.run(
        command, cwd=str(root), capture_output=True, text=True, check=False,
    ).returncode == 0


def empty_run_status(
    root: Path,
    paths: Sequence[str],
    passthrough: Sequence[str],
    *,
    splits: int,
    group: int,
) -> int:
    """Name why nothing ran, and say whether that is a pass or a verdict."""
    if splits > 1 and collects_anything(root, paths, passthrough):
        print(
            f"ci_selection_run group {group}/{splits} drew no test from the "
            "split; the other groups carry the selection",
            flush=True,
        )
        return 0
    print(
        "Error: ci_selection_run collected no test: the dispatched paths or "
        "filters match nothing in this tree",
        flush=True,
    )
    return EXIT_NO_TESTS_COLLECTED


def run_selection(
    root: Path,
    *,
    base_sha: str,
    expected_head_sha: str,
    passthrough: Sequence[str],
    splits: int = 1,
    group: int = 1,
    log_path: Path | None = None,
) -> int:
    """Select, run, and mirror the output; return pytest's exit status."""
    mismatch = checkout_mismatch(root, expected_head_sha)
    if mismatch:
        print(mismatch, flush=True)
        return EXIT_USAGE
    if group < 1 or group > splits:
        print(
            f"Error: ci_selection_run was handed group {group} of {splits}; "
            "the workflow matrix and the split it passes come from one plan "
            "and have drifted apart",
            flush=True,
        )
        return EXIT_USAGE
    paths: list[str] = []
    if base_sha:
        selected = selection_paths(root, base_sha)
        if selected is None:
            print(NO_SELECTED_TESTS, flush=True)
            return 0
        paths = selected
    if not paths and not has_positional_args(passthrough):
        print(
            "Error: ci_selection_run has nothing to run: no base_sha to "
            "select from and no explicit pytest paths were dispatched",
            flush=True,
        )
        return EXIT_USAGE
    command = pytest_command(paths, passthrough, splits=splits, group=group)
    print(f"$ {shlex.join(command)}", flush=True)
    process = subprocess.Popen(
        command,
        cwd=str(root),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert process.stdout is not None
    with Path(log_path or root / OUTPUT_LOG).open("w", encoding="utf-8") as log:
        for line in process.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            log.write(line)
    status = process.wait()
    if status == EXIT_NO_TESTS_COLLECTED:
        return empty_run_status(
            root, paths, passthrough, splits=splits, group=group
        )
    return status


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


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    """Parse the dispatch arguments and this shard's place in the split."""
    parser = argparse.ArgumentParser(
        prog="ci_selection_run",
        description=(
            "Run the impacted pytest selection for (base_sha, head_sha) on "
            "this checkout, mirroring output to the uploaded log."
        ),
    )
    add_dispatch_arguments(parser)
    parser.add_argument(
        "--splits",
        default="",
        help="How many shards the plan cut this selection into; empty runs "
        "the whole selection here.",
    )
    parser.add_argument(
        "--group",
        default="",
        help="Which of those shards this job is, counting from 1.",
    )
    return parser.parse_args(list(argv))


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    root = Path(args.root or Path.cwd()).resolve()
    return run_selection(
        root,
        base_sha=args.base_sha.strip(),
        expected_head_sha=args.head_sha.strip(),
        passthrough=shlex.split(args.pytest_args),
        splits=shard_number(args.splits),
        group=shard_number(args.group),
    )


__all__ = [
    "CI_WORKERS",
    "EXIT_NO_TESTS_COLLECTED",
    "EXIT_USAGE",
    "add_dispatch_arguments",
    "checkout_mismatch",
    "collects_anything",
    "empty_run_status",
    "has_positional_args",
    "head_sha",
    "main",
    "parse_args",
    "positional_args",
    "pytest_command",
    "run_selection",
    "selection_paths",
]


if __name__ == "__main__":  # pragma: no cover — exercised via subprocess
    raise SystemExit(main())
