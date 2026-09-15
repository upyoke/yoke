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

The whole suite is always worth :data:`SHARD_COUNT` shards. A change-scoped
selection is not: it can be three tests or most of the suite, so
:func:`split_count` sizes it against that same fixed cost from the committed
profile, and small selections stay on the one runner they already used.

``least_duration`` greedily assigns the slowest tests first using the committed
timing profile, so the profile has to stay current: tests missing from it are
treated as unknown and land wherever the greedy pass puts them, which is how a
stale profile turns more shards into worse balance rather than better. A lagging
profile is also invisible to :func:`profiled_size`, so it shows up as a
selection sized far below the work it then does.

:mod:`yoke_core.tools.ci_durations_refresh` rebuilds it from a full-suite CI
run and owns what a stored second means: a group's sum is the wall seconds that
group is expected to take, which is the unit
:data:`MIN_SHARD_PROFILE_SECONDS` is written in.

``-n auto`` mirrors ``DEFAULT_PARALLEL_WORKERS`` in
``runtime/api/tools/_pytest_parallel.py`` — the canonical home the local
``run_tests`` / ``watch_pytest`` runners read. CI pins flat ``auto`` on purpose:
hosted runners should use every core, not the RAM-aware cliff that can drop a
constrained box to ``-n 1``. The outer shard cuts total wall time; xdist still
uses every core inside each shard.
"""

from __future__ import annotations

import argparse
import json
import math
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

# Profiled test seconds one shard is worth carrying, deliberately well under
# the ~150s break-even above. Profiled seconds are a floor: `profiled_size`
# sees only tests the committed profile already holds, and the tests a change
# adds are exactly the ones no full-suite run has measured yet, so a
# change-scoped selection always profiles at less than it runs. Budgeting at
# the break-even would assume that gap away. Erring low is also the cheaper
# side to be wrong on — one shard too many costs that runner's fixed setup
# beside work that was going to run anyway, one too few costs the selection
# the wall time it could have split.
MIN_SHARD_PROFILE_SECONDS = 60.0


def shard_list(count: int = SHARD_COUNT) -> list[int]:
    """The shard numbers, one per matrix job."""
    return list(range(1, count + 1))


def fan_out_lines() -> list[str]:
    """The ``key=value`` lines the workflow reads back as a job output."""
    shards = ",".join(str(shard) for shard in shard_list())
    return [f"shards=[{shards}]"]


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


def normalize_profile_target(root: Path, target: str) -> str | None:
    """Repo-relative profile spelling for *target*, or None if outside *root*.

    The committed profile keys are repo-relative node ids. Equivalent
    ``./relative``, in-checkout absolute, node-id, ``.`` and checkout-root
    spellings must therefore collapse to the same path before matching.
    A target that resolves outside *root* is dropped so it cannot silently
    match unrelated profile data.
    """
    root = root.resolve()
    path_text, sep, node = target.partition("::")
    suffix = f"::{node}" if sep else ""
    text = path_text.strip()
    if not text or text == ".":
        return f".{suffix}" if suffix else "."
    relative = text[2:] if text.startswith("./") else text
    while relative.startswith("./"):
        relative = relative[2:]
    if not relative or relative == ".":
        candidate = root
    else:
        candidate = Path(relative) if Path(relative).is_absolute() else (root / relative)
    try:
        rel = candidate.resolve().relative_to(root)
    except ValueError:
        return None
    rel_text = rel.as_posix()
    if rel_text == ".":
        return f".{suffix}" if suffix else "."
    return rel_text + suffix


def profiled_size(root: Path, targets: Sequence[str]) -> tuple[float, int]:
    """Profiled seconds and profiled test count for *targets*.

    Node ids in the committed profile are repo-relative, so a selected file,
    a directory, and a single node id all match by prefix. Tests the profile
    has never seen are invisible here, which makes this a floor: an
    underestimate costs a shard, never coverage.
    """
    try:
        durations = json.loads(
            (root / DURATIONS_PATH).read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return 0.0, 0
    normalized = [
        spelling
        for target in targets
        if (spelling := normalize_profile_target(root, target)) is not None
    ]
    if any(spelling == "." or spelling.startswith(".::") for spelling in normalized):
        return sum(float(duration) for duration in durations.values()), len(durations)
    files = {target for target in normalized if target.endswith(".py")}
    others = tuple(
        target.rstrip("/") for target in normalized if not target.endswith(".py")
    )
    seconds = 0.0
    profiled = 0
    for node_id, duration in durations.items():
        path = node_id.split("::", 1)[0]
        if path in files or _matches_target(node_id, path, others):
            seconds += float(duration)
            profiled += 1
    return seconds, profiled


def _matches_target(node_id: str, path: str, targets: Sequence[str]) -> bool:
    """Whether *node_id* is under any directory or node-id target."""
    return any(
        node_id == target
        or node_id.startswith(f"{target}::")
        or path.startswith(f"{target}/")
        for target in targets
    )


def split_count(profiled_seconds: float, profiled_tests: int) -> int:
    """How many shards a selection of this size earns.

    One shard per :data:`MIN_SHARD_PROFILE_SECONDS` of profiled test time,
    rounded UP: the remainder past a whole budget is real test time that has
    to run somewhere, and because the profile undercounts, that remainder is
    itself a floor. Rounding it down hands a selection the narrower fan-out
    of the two readings every time.

    The count is then capped at the full suite's own shard count and at the
    number of tests the profile knows about: a group holding no test at all
    reports "no tests ran" instead of a verdict, so the count never exceeds
    what can fill it, and a selection with nothing profiled still runs on the
    one shard it always did.
    """
    earned = math.ceil(profiled_seconds / MIN_SHARD_PROFILE_SECONDS)
    return max(1, min(SHARD_COUNT, earned, profiled_tests))


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
        emit_output_lines(
            fan_out_lines(), write_github_output=args.write_github_output
        )
        return 0
    return _run_shard(args.group)


__all__ = [
    "DURATIONS_PATH",
    "JUNIT_REPORT",
    "MIN_SHARD_PROFILE_SECONDS",
    "OUTPUT_LOG",
    "SHARD_COUNT",
    "SUITE_PATHS",
    "emit_output_lines",
    "fan_out_lines",
    "main",
    "normalize_profile_target",
    "profiled_size",
    "pytest_command",
    "shard_list",
    "shard_number",
    "split_count",
]


if __name__ == "__main__":
    raise SystemExit(main())
