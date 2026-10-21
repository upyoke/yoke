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

An impacted selection is collected the way full CI collects: pytest is
handed the project's test roots, and the plugin in
:mod:`yoke_core.tools.ci_selection_collect` skips every file outside the
selection before importing it. Explicit paths dispatched without a base run
exactly as named.

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
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Mapping, Sequence

from yoke_core.tools._pytest_parallel import has_explicit_workers
from yoke_core.tools._watch_pytest_args import NO_SELECTED_TESTS
from yoke_core.tools.ci_selection_collect import SELECTION_FILE_ENV
from yoke_core.tools.ci_selection_inputs import (
    EXIT_USAGE,
    add_dispatch_arguments,
    checkout_mismatch,
    has_positional_args,
    selection_paths,
    split_args,
)
from yoke_core.tools.ci_shards import (
    DURATIONS_PATH,
    OUTPUT_LOG,
    XDIST_ARGS,
    shard_number,
)

#: pytest's status when its collection left nothing to run. For one shard of
#: several that can mean the split emptied this group rather than the
#: selection finding nothing, which the log's deselected count settles.
EXIT_NO_TESTS_COLLECTED = 5

#: The plugin that narrows root collection to the selection file.
COLLECT_PLUGIN = "yoke_core.tools.ci_selection_collect"


def pytest_command(
    paths: Sequence[str],
    passthrough: Sequence[str],
    *,
    splits: int = 1,
    group: int = 1,
) -> list[str]:
    """The pytest invocation for *paths* plus the caller's own arguments.

    *paths* are the test roots for an impacted selection, which the collect
    plugin then narrows, or empty for explicit dispatched paths. One shard of
    several adds the split the plan sized, through the same duration-balanced
    machinery and profile the full suite splits with: the selection each
    group collects is identical, so every selected test is assigned to
    exactly one of them. Workers and scheduling are full CI's own unless the
    caller chose a worker count.
    """
    argv = [sys.executable, "-m", "pytest", *paths, *passthrough]
    if not has_explicit_workers(passthrough):
        argv.extend(XDIST_ARGS)
    if splits > 1:
        argv.extend(("--splits", str(splits), "--group", str(group)))
        argv.extend(("--splitting-algorithm", "least_duration"))
        argv.extend(("--durations-path", DURATIONS_PATH))
    return argv


def root_collection(
    root: Path, selected: Sequence[str], passthrough: Sequence[str]
) -> tuple[list[str], list[str], Path]:
    """``(paths, options, selection_file)`` for an impacted selection.

    The dispatched positional targets join the selection file rather than
    the command line, so pytest walks only the roots full CI walks. A
    target outside every root is never reached by that walk, so it is also
    named on the command line: a selected test is never silently dropped.
    """
    from yoke_core.tools.impacted_project_test_roots import resolve_test_roots

    targets, options = split_args(passthrough)
    roots = list(resolve_test_roots(str(root)))
    prefixes = tuple(anchor.rstrip("/") for anchor in roots)
    outside = [
        target
        for target in dict.fromkeys((*selected, *targets))
        if not any(
            (path := target.partition("::")[0].rstrip("/")) == prefix
            or path.startswith(f"{prefix}/")
            for prefix in prefixes
        )
    ]
    handle, name = tempfile.mkstemp(prefix="yoke-ci-selection-", suffix=".txt")
    with os.fdopen(handle, "w", encoding="utf-8") as selection:
        selection.write("".join(f"{path}\n" for path in (*selected, *targets)))
    return [*roots, *outside], ["-p", COLLECT_PLUGIN, *options], Path(name)


def collects_anything(
    root: Path,
    paths: Sequence[str],
    passthrough: Sequence[str],
    env: Mapping[str, str] | None = None,
) -> bool:
    """Whether the unsplit selection collects a test at all in *root*.

    Asked only when a run reported none: pytest answers it in its exit
    status, which separates a group the split left empty (the selection
    collects, the other groups carry it) from a selection that matches
    nothing here (every group reports the same, and it is a real failure).
    """
    command = [sys.executable, "-m", "pytest", *paths, *passthrough]
    command += ["--collect-only", "-q", "-n", "0"]
    print(f"$ {shlex.join(command)}", flush=True)
    completed = subprocess.run(
        command, cwd=str(root), env=env, capture_output=True, text=True, check=False
    )
    return completed.returncode == 0


def empty_run_status(
    root: Path,
    paths: Sequence[str],
    passthrough: Sequence[str],
    *,
    splits: int,
    group: int,
    env: Mapping[str, str] | None = None,
) -> int:
    """Name why nothing ran, and say whether that is a pass or a verdict."""
    if splits > 1 and collects_anything(root, paths, passthrough, env):
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
    args = list(passthrough)
    env: dict[str, str] | None = None
    if base_sha:
        selected = selection_paths(root, base_sha)
        if selected is None:
            print(NO_SELECTED_TESTS, flush=True)
            return 0
        paths, args, selection_file = root_collection(root, selected, passthrough)
        env = {**os.environ, SELECTION_FILE_ENV: str(selection_file)}
        print(
            f"ci_selection_run: collecting {len(selected)} selected paths from "
            f"{' '.join(paths)}; selection file {selection_file}",
            flush=True,
        )
    elif not has_positional_args(passthrough):
        print(
            "Error: ci_selection_run has nothing to run: no base_sha to "
            "select from and no explicit pytest paths were dispatched",
            flush=True,
        )
        return EXIT_USAGE
    command = pytest_command(paths, args, splits=splits, group=group)
    print(f"$ {shlex.join(command)}", flush=True)
    process = subprocess.Popen(
        command,
        cwd=str(root),
        env=env,
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
            root, paths, args, splits=splits, group=group, env=env
        )
    return status


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
    "COLLECT_PLUGIN",
    "EXIT_NO_TESTS_COLLECTED",
    "collects_anything",
    "empty_run_status",
    "main",
    "parse_args",
    "pytest_command",
    "root_collection",
    "run_selection",
]


if __name__ == "__main__":  # pragma: no cover — exercised via subprocess
    raise SystemExit(main())
