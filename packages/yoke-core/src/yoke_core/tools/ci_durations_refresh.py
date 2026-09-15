"""Rebuild the committed timing profile from a full-suite CI run's artifacts.

:mod:`yoke_core.tools.ci_shards` sizes and balances against
:data:`~yoke_core.tools.ci_shards.DURATIONS_PATH`, and everything that profile
has never seen is invisible to it: a selection reaching newly added tests is
sized far below the work it then does. Keeping it current is this module's
whole job.

The measurement is a full-suite CI run, which is the only place the whole suite
runs on the fleet that will run the shards — never a local sweep, whose machine
and parallelism are not the ones being predicted. Every shard of that run
uploads a ``pytest-report.xml``, and together they cover the suite exactly once.

Those per-test times are measured under ``-n auto``, so each carries the
contention of whatever ran beside it and their sum exceeds the wall time the
session actually took. Stored raw they would inflate every future estimate, so
each test is stored as its share of the run's summed case time applied to the
wall time the run really spent: relative weights — all ``least_duration`` reads
— are untouched, and a group's stored sum stays readable as the wall seconds it
predicts, which is the unit
:data:`~yoke_core.tools.ci_shards.MIN_SHARD_PROFILE_SECONDS` is written in.

Refreshing after a green full-suite run on the default branch::

    python3 -m yoke_core.tools.ci_durations_refresh --run <run-id>

The run id must name a full-suite run, not a selection run: a selection covers
only its own change, and a profile rebuilt from one would forget every test the
selection did not reach.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from yoke_core.tools.ci_shards import DURATIONS_PATH, JUNIT_REPORT

#: ``pytest-output-<python-version>-<shard>``, the name full-suite CI gives each
#: shard's artifact. A selection run's ``pytest-output-selection-N`` carries no
#: report and does not match, which is how the wrong run is caught.
SHARD_ARTIFACT = re.compile(r"^pytest-output-(?P<python>\d+\.\d+)-(?P<shard>\d+)$")


@dataclass(frozen=True)
class ShardTiming:
    """One shard's measured session wall time and its per-test seconds."""

    artifact: str
    wall_seconds: float
    case_seconds: dict[str, float]


def node_id(root: Path, classname: str, name: str, cache: dict[str, bool]) -> str:
    """The repo-relative node id a junit ``classname``/``name`` pair names.

    junit spells the module as a dotted path, so the module ends at the last
    component that is a file in *root* and everything after it is class
    nesting. Resolving against the checkout rather than guessing means a
    profile can only ever name tests this tree actually holds.
    """
    parts = classname.split(".")
    for cut in range(len(parts), 0, -1):
        candidate = "/".join(parts[:cut]) + ".py"
        if candidate not in cache:
            cache[candidate] = (root / candidate).is_file()
        if cache[candidate]:
            return "::".join([candidate, *parts[cut:], name])
    raise SystemExit(
        f"no module file in {root} for junit classname {classname!r}. Refresh "
        "from a run of the commit this checkout is on, or check the checkout out "
        "at the run's commit first."
    )


def read_shards(artifacts: Path, root: Path, python_version: str) -> list[ShardTiming]:
    """Every shard report *artifacts* holds for *python_version*."""
    cache: dict[str, bool] = {}
    shards: list[ShardTiming] = []
    for directory in sorted(artifacts.iterdir()):
        matched = SHARD_ARTIFACT.match(directory.name)
        if not matched or matched.group("python") != python_version:
            continue
        report = directory / JUNIT_REPORT
        if not report.is_file():
            raise SystemExit(
                f"{directory.name} has no {JUNIT_REPORT}. Only a full-suite run "
                "uploads one; a selection run cannot refresh the profile."
            )
        suite = ElementTree.parse(report).getroot().find("testsuite")
        if suite is None:
            raise SystemExit(f"{report} holds no testsuite element")
        seconds = {
            node_id(root, case.attrib["classname"], case.attrib["name"], cache): float(
                case.attrib["time"]
            )
            for case in suite.iter("testcase")
        }
        shards.append(
            ShardTiming(directory.name, float(suite.attrib["time"]), seconds)
        )
    return shards


def python_versions(artifacts: Path) -> list[str]:
    """The Python versions *artifacts* holds shard reports for."""
    found = {
        matched.group("python")
        for directory in artifacts.iterdir()
        if (matched := SHARD_ARTIFACT.match(directory.name))
    }
    return sorted(found)


def merged_case_seconds(shards: Sequence[ShardTiming]) -> dict[str, float]:
    """Every shard's tests in one mapping, refusing any test two shards ran.

    The split hands each test to exactly one group, so a node id in two shards
    means the run under measurement did not cover the suite once — and a
    profile built from it would carry one test's time twice.
    """
    merged: dict[str, float] = {}
    for shard in shards:
        for node, seconds in shard.case_seconds.items():
            if node in merged:
                raise SystemExit(
                    f"{node} ran in more than one shard of this run, so its "
                    "shards did not cover the suite exactly once"
                )
            merged[node] = seconds
    return merged


def normalized_profile(shards: Sequence[ShardTiming]) -> dict[str, float]:
    """Each test's share of the measured cost, scaled to the wall time spent."""
    measured = sum(sum(shard.case_seconds.values()) for shard in shards)
    wall = sum(shard.wall_seconds for shard in shards)
    if measured <= 0.0:
        raise SystemExit("the run's shards measured no test time at all")
    return {
        node: seconds / measured * wall
        for node, seconds in sorted(merged_case_seconds(shards).items())
    }


def download(run_id: str, repo: str, destination: Path) -> None:
    """Fetch *run_id*'s shard artifacts into *destination*."""
    completed = subprocess.run(
        ["gh", "run", "download", run_id, "-R", repo, "-D", str(destination)],
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise SystemExit(
            f"gh run download failed for {repo} run {run_id}: "
            f"{completed.stderr.strip() or completed.stdout.strip()}"
        )


def refresh(artifacts: Path, root: Path, python_version: str | None) -> int:
    """Write the profile *artifacts* measures, and report what it measured."""
    available = python_versions(artifacts)
    if not available:
        raise SystemExit(
            f"no pytest-output-<python-version>-<shard> artifacts under {artifacts}. "
            "A selection run uploads pytest-output-selection-N and holds no report; "
            "name a full-suite run instead."
        )
    if python_version is None:
        if len(available) > 1:
            raise SystemExit(
                f"this run covers the suite once per Python version {available}; "
                "pass --python-version to choose which one to store"
            )
        python_version = available[0]
    elif python_version not in available:
        raise SystemExit(
            f"this run holds no {python_version} shards; it has {available}"
        )

    shards = read_shards(artifacts, root, python_version)
    profile = normalized_profile(shards)
    (root / DURATIONS_PATH).write_text(
        json.dumps(profile, indent=4) + "\n", encoding="utf-8"
    )

    measured = sum(sum(shard.case_seconds.values()) for shard in shards)
    wall = sum(shard.wall_seconds for shard in shards)
    print(
        f"ci_durations_refresh: python={python_version} shards={len(shards)} "
        f"tests={len(profile)} measured_case_seconds={measured:.1f} "
        f"session_wall_seconds={wall:.1f} stored_share={wall / measured:.5f} "
        f"-> {root / DURATIONS_PATH}"
    )
    for shard in shards:
        predicted = sum(profile[node] for node in shard.case_seconds)
        error = 100.0 * (predicted - shard.wall_seconds) / shard.wall_seconds
        print(
            f"  {shard.artifact}: predicted={predicted:.1f}s "
            f"observed={shard.wall_seconds:.1f}s error={error:+.1f}%"
        )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ci_durations_refresh", description=__doc__
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--run", help="Full-suite CI run id to download artifacts from.")
    source.add_argument(
        "--artifacts",
        type=Path,
        help="Directory of already-downloaded shard artifacts.",
    )
    parser.add_argument("--repo", default="upyoke/yoke", help="Repository for --run.")
    parser.add_argument("--root", type=Path, help="Checkout to write the profile in.")
    parser.add_argument(
        "--python-version",
        help="Which version's shards to store when the run covers several.",
    )
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    root = Path(args.root or Path.cwd()).resolve()

    if args.artifacts:
        return refresh(args.artifacts.resolve(), root, args.python_version)
    with tempfile.TemporaryDirectory() as downloaded:
        destination = Path(downloaded)
        download(args.run, args.repo, destination)
        return refresh(destination, root, args.python_version)


__all__ = [
    "SHARD_ARTIFACT",
    "ShardTiming",
    "download",
    "main",
    "merged_case_seconds",
    "node_id",
    "normalized_profile",
    "python_versions",
    "read_shards",
    "refresh",
]


if __name__ == "__main__":
    raise SystemExit(main())
