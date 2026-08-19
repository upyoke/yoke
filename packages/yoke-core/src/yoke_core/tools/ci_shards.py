"""One source for how CI cuts the suite into shards.

The suite is split two ways that must agree: the workflow matrix fans out one
job per shard, and pytest is told how many shards exist so it can select the
matching group. Writing those as two literals is a silent-failure trap — a
matrix of four against ``--splits 8`` runs half the suite and still reports
green, because every job passes the slice it was given. So the workflow holds
neither number. It asks this module for the fan-out, and asks this module to
run the suite; :data:`SHARD_COUNT` is the only place the value exists.

Sizing: a shard pays a fixed ~41s of setup (checkout, Python, uv, dependencies,
Postgres) against its share of the pytest wall time, so splitting further keeps
paying off until the fixed cost stops being noise. Below roughly 150s of tests
per shard the overhead crosses 20% and the profile's existing imbalance gets
relatively worse.

``least_duration`` greedily assigns the slowest tests first using the committed
timing profile, so the profile has to stay current: tests missing from it are
treated as unknown and land wherever the greedy pass puts them, which is how a
stale profile turns more shards into worse balance rather than better.

``-n auto`` mirrors ``DEFAULT_PARALLEL_WORKERS`` in
``runtime/api/tools/_pytest_parallel.py`` — the canonical home the local
``run_tests`` / ``watch_pytest`` runners read. CI pins flat ``auto`` on purpose:
hosted runners should use every core, not the RAM-aware cliff that can drop a
constrained box to ``-n 1``. The outer shard cuts total wall time; xdist still
uses every core inside each shard.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Sequence


# The number of shards the suite is cut into, per Python version. The workflow
# matrix and pytest's --splits both derive from this and cannot disagree.
SHARD_COUNT = 8

# The three roots that are the full suite. A partial anchor silently demotes a
# package's top-level conftest and collection fails.
SUITE_PATHS = ("runtime/api/", "runtime/harness/", "tests/")

DURATIONS_PATH = ".test_durations"
OUTPUT_LOG = "pytest-output.txt"
JUNIT_REPORT = "pytest-report.xml"


def shard_list() -> list[int]:
    """The shard numbers, one per matrix job."""
    return list(range(1, SHARD_COUNT + 1))


def fan_out_lines() -> list[str]:
    """The ``key=value`` lines the workflow reads back as a job output."""
    shards = ",".join(str(shard) for shard in shard_list())
    return [f"shards=[{shards}]"]


def pytest_command(group: int) -> list[str]:
    """The exact suite invocation for one shard."""
    return [
        "uv", "run", "python", "-m", "pytest", *SUITE_PATHS,
        "-n", "auto",
        "--dist", "worksteal",
        "--splits", str(SHARD_COUNT),
        "--group", str(group),
        "--splitting-algorithm", "least_duration",
        "--durations-path", DURATIONS_PATH,
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
    process = subprocess.Popen(
        pytest_command(group),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert process.stdout is not None
    with Path(OUTPUT_LOG).open("w", encoding="utf-8") as log:
        for line in process.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            log.write(line)
    return process.wait()


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
        lines = fan_out_lines()
        destination = os.environ.get("GITHUB_OUTPUT") if (
            args.write_github_output
        ) else None
        if destination:
            with Path(destination).open("a", encoding="utf-8") as handle:
                handle.write("".join(f"{line}\n" for line in lines))
        else:
            print("\n".join(lines))
        return 0
    return _run_shard(args.group)


__all__ = [
    "DURATIONS_PATH",
    "JUNIT_REPORT",
    "OUTPUT_LOG",
    "SHARD_COUNT",
    "SUITE_PATHS",
    "fan_out_lines",
    "main",
    "pytest_command",
    "shard_list",
]


if __name__ == "__main__":
    raise SystemExit(main())
