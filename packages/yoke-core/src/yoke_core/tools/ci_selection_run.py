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
from yoke_core.tools.ci_shards import OUTPUT_LOG

#: Every core of the runner, flat: the RAM-aware cliff the local runners
#: apply protects a shared workstation, which a hosted runner is not.
CI_WORKERS = "auto"

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


def pytest_command(paths: Sequence[str], passthrough: Sequence[str]) -> list[str]:
    """The pytest invocation for *paths* plus the caller's own arguments."""
    argv = [sys.executable, "-m", "pytest", *paths, *passthrough]
    if not has_explicit_workers(passthrough):
        argv.extend(["-n", CI_WORKERS])
    return argv


def has_positional_args(args: Sequence[str]) -> bool:
    """Whether *args* name any collection target of their own."""
    skip_next = False
    for token in args:
        if skip_next:
            skip_next = False
            continue
        if token.startswith("-"):
            skip_next = pytest_flag_consumes_value(token)
            continue
        return True
    return False


def run_selection(
    root: Path,
    *,
    base_sha: str,
    expected_head_sha: str,
    passthrough: Sequence[str],
    log_path: Path | None = None,
) -> int:
    """Select, run, and mirror the output; return pytest's exit status."""
    actual = head_sha(root)
    if expected_head_sha and actual != expected_head_sha:
        print(
            f"Error: ci_selection_run checked out {actual[:12] or 'no commit'} "
            f"but the dispatch named {expected_head_sha[:12]}; the workflow "
            "must check out inputs.head_sha before running the selection",
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
    command = pytest_command(paths, passthrough)
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
    return process.wait()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ci_selection_run",
        description=(
            "Run the impacted pytest selection for (base_sha, head_sha) on "
            "this checkout, mirroring output to the uploaded log."
        ),
    )
    parser.add_argument(
        "--base-sha",
        default="",
        help="Merge base the selection is computed against; empty runs "
        "--pytest-args as given.",
    )
    parser.add_argument(
        "--head-sha",
        default="",
        help="Commit the dispatch named; the run refuses any other checkout.",
    )
    parser.add_argument(
        "--pytest-args",
        default="",
        help="Shell-quoted bare pytest arguments appended to the selection.",
    )
    parser.add_argument(
        "--root",
        default=None,
        help="Checkout to run in (default: the working directory).",
    )
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    root = Path(args.root or Path.cwd()).resolve()
    return run_selection(
        root,
        base_sha=args.base_sha.strip(),
        expected_head_sha=args.head_sha.strip(),
        passthrough=shlex.split(args.pytest_args),
    )


__all__ = [
    "CI_WORKERS",
    "EXIT_USAGE",
    "has_positional_args",
    "head_sha",
    "main",
    "pytest_command",
    "run_selection",
    "selection_paths",
]


if __name__ == "__main__":  # pragma: no cover — exercised via subprocess
    raise SystemExit(main())
