"""Collect fixture facts once and publish balanced, disjoint CI file lists."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from yoke_core.tools.ci_shards import SHARD_COUNT, SUITE_PATHS

FACTS_ENV = "YOKE_CI_SHARD_FACTS"
GROUPS_PATH = "ci-shard-groups.json"


def pytest_collection_finish(session):
    destination = os.environ.get(FACTS_ENV)
    if not destination:
        return
    from runtime.ci_test_selection import PRODUCT_WHEEL_FIXTURES, version_independent

    records = [
        {"nodeid": item.nodeid,
         "independent": bool(version_independent(item.nodeid, item.fixturenames)
                             or item.get_closest_marker("ci_version_independent")),
         "wheel": not PRODUCT_WHEEL_FIXTURES.isdisjoint(item.fixturenames)}
        for item in session.items
    ]
    Path(destination).write_text(json.dumps(records) + "\n", encoding="utf-8")


def group_files(records, durations, tracked, count=SHARD_COUNT):
    """Greedily place whole fixture units; unknown files get a mean file weight."""
    if count < 1 or not records:
        raise ValueError("ci_shard_groups_empty: restore collection before grouping")
    files = {}
    wheels = set()
    for record in records:
        filename = record["nodeid"].split("::", 1)[0]
        files.setdefault(filename, []).append(record["nodeid"])
        if record["wheel"]:
            wheels.add(filename)
    missing = files.keys() - set(tracked)
    if missing:
        raise ValueError(f"ci_shard_files_untracked: git add collected files: {sorted(missing)}")
    weights = {filename: sum(durations[node] for node in nodes if node in durations)
               for filename, nodes in files.items()}
    known = [weight for weight in weights.values() if weight > 0]
    average = sum(known) / len(known) if known else 1.0
    units = {}
    for filename in tracked:
        if filename not in files:
            continue
        unit = "product wheel files" if filename in wheels else filename
        names, weight = units.get(unit, ([], 0))
        units[unit] = (names + [filename], weight + (weights[filename] or average))
    groups, totals = [[] for _ in range(count)], [0.0] * count
    for names, weight in sorted(units.values(), key=lambda unit: -unit[1]):
        index = min(range(count), key=lambda index: (totals[index], index))
        groups[index].extend(names)
        totals[index] += weight
    if any(not group for group in groups):
        raise ValueError("ci_shard_group_empty: reduce the declared shard count before fan-out")
    return groups


def build_groups(records, durations, tracked, count=SHARD_COUNT):
    return {scope: group_files(
        [record for record in records if scope == "all" or not record["independent"]],
        durations, tracked, count,
    ) for scope in ("all", "interpreter")}


def shard_files(path: Path, scope: str, group: int):
    try:
        groups = json.loads(path.read_text(encoding="utf-8"))[scope]
        if len(groups) != SHARD_COUNT or not 1 <= group <= SHARD_COUNT:
            raise ValueError("group count does not match fan-out")
        files = groups[group - 1]
        if not files or any(not isinstance(name, str) or "::" in name
                            or Path(name).is_absolute() or ".." in Path(name).parts
                            or not name.endswith(".py") for name in files):
            raise ValueError("invalid or empty file list")
        return files
    except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
        raise SystemExit(
            f"ci_shard_groups_invalid: {path}: {error}; regenerate and download "
            "this run's ci-shard-groups artifact before running pytest"
        ) from error


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(GROUPS_PATH))
    args = parser.parse_args(argv)
    facts = args.output.with_suffix(".facts.json")
    started = time.monotonic()
    environment = dict(os.environ, **{FACTS_ENV: str(facts.resolve()),
                                     "YOKE_CI_PYTHON_SCOPE": "all"})
    try:
        with args.output.with_suffix(".collection.txt").open("w") as output:
            result = subprocess.run(
                [sys.executable, "-m", "pytest", *SUITE_PATHS, "--collect-only",
                 "-q", "-p", "no:xdist", "-p", "yoke_core.tools.ci_shard_groups"],
                env=environment, stdout=output, stderr=subprocess.STDOUT, check=False,
            )
        if result.returncode:
            raise ValueError("ci_shard_collection_failed: inspect ci-shard-groups.collection.txt")
        tracked = subprocess.check_output(["git", "ls-files", "-z"], text=True).split("\0")
        groups = build_groups(json.loads(facts.read_text()),
                              json.loads(Path(".test_durations").read_text()), tracked)
        args.output.write_text(json.dumps(groups, indent=2) + "\n")
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"ci_shard_groups_failed: {error}; repair collection and regenerate file groups")
        return 1
    print(f"CI file grouping: {time.monotonic() - started:.2f}s; "
          + json.dumps({scope: sum(map(len, files)) for scope, files in groups.items()}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
