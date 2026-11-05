"""Run CI shards using file groups published by one fixture-aware collection.

The collection filter preserves all suite-root conftests while skipping files
outside the assigned group before import. Every worker collects only its group.
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
# matrix and published file groups both derive from this.
SHARD_COUNT = 16

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

# Recent healthy probes topped out at 0.0226s; stalled hosts measured 0.0678s
# and 0.0895s. Keep a wide margin above healthy variation (ci-shards.md).
MAX_PYTHON_LOOP_SECONDS = 0.05


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
        "-p", "yoke_core.tools.ci_selection_collect",
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
    from yoke_core.tools.ci_shard_groups import GROUPS_PATH, shard_files
    from yoke_core.tools.ci_selection_collect import SELECTION_FILE_ENV

    files = shard_files(Path(GROUPS_PATH), os.environ.get("YOKE_CI_PYTHON_SCOPE", "all"), group)
    selection = Path(".yoke/tmp/ci-shard-files.txt")
    selection.parent.mkdir(parents=True, exist_ok=True)
    selection.write_text("\n".join(files) + "\n", encoding="utf-8")
    environment = dict(os.environ, **{SELECTION_FILE_ENV: str(selection.resolve())})
    assignment = f"CI shard {group}/{SHARD_COUNT}: {len(files)} assigned files\n"
    print(assignment, end="", flush=True)
    with Path(OUTPUT_LOG).open("a", encoding="utf-8") as log:
        log.write(assignment)
    process = subprocess.Popen(
        pytest_command(group),
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert process.stdout is not None
    with Path(OUTPUT_LOG).open("a", encoding="utf-8") as log:
        for line in process.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            log.write(line)
    return process.wait()


def check_runner_capacity() -> int:
    """Refuse a slow runner before the workflow starts its pytest step."""
    measurements = runner_capacity()
    capacity = "CI runner capacity: " + json.dumps(measurements, sort_keys=True)
    print(capacity, flush=True)
    with Path(OUTPUT_LOG).open("w", encoding="utf-8") as log:
        log.write(capacity + "\n")
        elapsed = measurements["python_loop_seconds"]
        if elapsed > MAX_PYTHON_LOOP_SECONDS:
            reason = (
                f"ci_runner_slow: runner refused before pytest; python_loop_seconds={elapsed:.6f} "
                f"exceeds {MAX_PYTHON_LOOP_SECONDS:.2f}s. "
                "Restore runner capacity; no test verdict was produced."
            )
            print(reason, flush=True)
            log.write(reason + "\n")
            return 1
    return 0


def runner_capacity() -> dict:
    """Measure local capacity before admitting a shard to pytest."""
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
    return {
        "cpu_model": model,
        "cpu_count": os.cpu_count(),
        "python_loop_seconds": sorted(samples)[1],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    fan_out = sub.add_parser("fan-out", help="Emit the matrix fan-out.")
    fan_out.add_argument(
        "--write-github-output",
        action="store_true",
        help="Append the fan-out to $GITHUB_OUTPUT instead of stdout.",
    )
    sub.add_parser("check-runner-capacity", help="Check capacity before pytest.")
    run = sub.add_parser("run", help="Run one shard of the suite.")
    run.add_argument("--group", type=int, required=True)
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.command == "fan-out":
        emit_output_lines(fan_out_lines(), write_github_output=args.write_github_output)
        return 0
    if args.command == "check-runner-capacity":
        return check_runner_capacity()
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
