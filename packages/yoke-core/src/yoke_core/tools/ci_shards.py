"""One shard count for the workflow matrix and pytest-split.

The newest Python endpoint runs the full suite. The oldest endpoint runs in
parallel on every CI event and excludes repository-only checks through
runtime.ci_test_selection before splitting. Both keep the same shard count
and required check names. Tree reuse requires evidence of both legs.

CI refreshes weights from a complete retained report set whose source includes
the committed timing baseline before fan-out,
then shares the same profile with every shard. The committed baseline is
refreshed through ci_durations_refresh; see docs/testing-verification/ci-shards.md.
Times measured under xdist are scaled to each report's actual suite wall time.
The greedy least_duration algorithm balances aggregate file weights; a file
stays on one shard and one worker so its fixtures are not repeated elsewhere.

A change-scoped selection is sized against the same profile by
ci_shard_sizing. CI uses every core inside each shard with -n auto and
loadfile scheduling.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Sequence


# The number of shards the suite is cut into, per Python version. The workflow
# matrix and pytest's --splits both derive from this and cannot disagree.
SHARD_COUNT = 8

# The three roots that are the full suite. A partial anchor silently demotes a
# package's top-level conftest and collection fails.
SUITE_PATHS = ("runtime/api/", "runtime/harness/", "tests/")

# How every CI pytest run, full shard or change-scoped selection, spreads over
# one runner: every core, whole files per worker so file-scoped fixtures are
# built once, and the duration-ordered file queue left as it is.
XDIST_ARGS = ("-n", "auto", "--dist", "loadfile", "--no-loadscope-reorder")

DURATIONS_PATH = ".test_durations"
OUTPUT_LOG = "pytest-output.txt"
JUNIT_REPORT = "pytest-report.xml"


def shard_list(count: int = SHARD_COUNT) -> list[int]:
    """The shard numbers, one per matrix job."""
    return list(range(1, count + 1))


def python_versions() -> list[str]:
    """CI endpoints from the standalone installer's support declaration."""
    root = Path(__file__).resolve().parents[5]
    helper = root / "packaging/public-installer/install.py"
    tree = ast.parse(helper.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "SUPPORTED_PYTHON"
            for target in node.targets
        ):
            endpoints = ast.literal_eval(node.value)
            return [f"{major}.{minor}" for major, minor in endpoints]
    raise SystemExit(
        "supported_python_declaration_missing: restore SUPPORTED_PYTHON in "
        "packaging/public-installer/install.py before running CI."
    )


def fan_out_lines() -> list[str]:
    """The ``key=value`` lines the workflow reads back as a job output."""
    shards = ",".join(str(shard) for shard in shard_list())
    versions = python_versions()
    return [
        f"shards=[{shards}]",
        f"python_versions={json.dumps(versions)}",
        f"python_latest={versions[-1]}",
    ]


def emit_output_lines(lines: Sequence[str], *, write_github_output: bool) -> None:
    """Append *lines* to ``$GITHUB_OUTPUT``, or print them when there is none."""
    destination = os.environ.get("GITHUB_OUTPUT") if write_github_output else None
    if destination:
        with Path(destination).open("a", encoding="utf-8") as handle:
            handle.write("".join(f"{line}\n" for line in lines))
        return
    print("\n".join(lines))


def shard_number(value: str, *, default: int = 1) -> int:
    """A shard number a workflow passed; empty means the unsharded default."""
    text = (value or "").strip()
    if not text:
        return default
    if not text.isdigit() or int(text) < 1:
        raise SystemExit(f"a shard number must be a positive integer, got {value!r}")
    return int(text)



def pytest_command(group: int) -> list[str]:
    """The exact suite invocation for one shard."""
    return [
        "uv",
        "run",
        "python",
        "-m",
        "pytest",
        *SUITE_PATHS,
        *XDIST_ARGS,
        "--splits",
        str(SHARD_COUNT),
        "--group",
        str(group),
        "--splitting-algorithm",
        "least_duration",
        "--durations-path",
        DURATIONS_PATH,
        "--tb=short",
        "--durations=25",
        f"--junitxml={JUNIT_REPORT}",
    ]


def _run_shard(group: int) -> int:
    """Run one shard, mirroring output to the uploaded log, and return its code.

    The log is written as the run proceeds rather than after it, so a shard
    killed mid-run still uploads what it had reached.
    """
    if group < 1 or group > SHARD_COUNT:
        raise SystemExit(f"shard {group} is outside 1..{SHARD_COUNT}")
    capacity = runner_capacity()
    print(capacity, flush=True)
    process = subprocess.Popen(
        pytest_command(group),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert process.stdout is not None
    with Path(OUTPUT_LOG).open("w", encoding="utf-8") as log:
        log.write(capacity + "\n")
        for line in process.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            log.write(line)
    return process.wait()


def runner_capacity() -> str:
    """Cheap diagnostic capacity evidence; it never controls test selection."""
    cpuinfo = Path("/proc/cpuinfo")
    model = "unavailable"
    try:
        model = next(
            (
                line.partition(":")[2].strip()
                for line in cpuinfo.read_text().splitlines()
                if line.startswith("model name")
            ),
            model,
        )
    except (OSError, UnicodeError):
        pass  # Missing capacity telemetry proves nothing and never blocks tests.
    samples = []
    for _ in range(3):
        started = time.perf_counter()
        sum(value * value for value in range(300_000))
        samples.append(time.perf_counter() - started)
    return "CI runner capacity: " + json.dumps(
        {
            "cpu_model": model,
            "cpu_count": os.cpu_count(),
            "python_loop_seconds": sorted(samples)[1],
        },
        sort_keys=True,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    fan_out = sub.add_parser("fan-out", help="Emit the matrix fan-out.")
    fan_out.add_argument(
        "--write-github-output",
        action="store_true",
        help="Append the fan-out to $GITHUB_OUTPUT instead of stdout.",
    )
    run = sub.add_parser("run", help="Run one shard of the suite.")
    run.add_argument("--group", type=int, required=True)
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.command == "fan-out":
        emit_output_lines(fan_out_lines(), write_github_output=args.write_github_output)
        return 0
    return _run_shard(args.group)


__all__ = [
    "DURATIONS_PATH",
    "JUNIT_REPORT",
    "OUTPUT_LOG",
    "SHARD_COUNT",
    "SUITE_PATHS",
    "emit_output_lines",
    "fan_out_lines",
    "main",
    "pytest_command",
    "shard_list",
    "shard_number",
]


if __name__ == "__main__":
    raise SystemExit(main())
