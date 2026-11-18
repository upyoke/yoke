"""Prove each selected test and module collection skip occurs exactly once.

`collect` records the unsplit collection while the shards run; `compare`
replays that manifest against every shard's JUnit report once they finish.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

from yoke_contracts.refusal_recovery import compose_refusal
from yoke_core.tools.ci_shards import SHARD_COUNT, SUITE_PATHS
from yoke_core.tools.ci_collection_skips import skipped_modules

pytest_plugins = ["yoke_core.tools.ci_collection_skips"]

MANIFEST_ENV = "YOKE_CI_COLLECTION_MANIFEST"
COLLECTION_LOG = "collection-output.txt"


def pytest_collection_finish(session):
    """Record the unsplit collection after interpreter-specific deselection."""
    destination = os.environ.get(MANIFEST_ENV)
    if not destination:
        return
    from _pytest.junitxml import mangle_test_address

    records = []
    for item in session.items:
        address = mangle_test_address(item.nodeid)
        records.append([".".join(address[:-1]), address[-1], item.nodeid])
    for module in skipped_modules():
        address = mangle_test_address(module)
        records.append([".".join(address[:-1]), address[-1], module])
    Path(destination).write_text(json.dumps(records) + "\n", encoding="utf-8")


def report_paths(directory: Path, python: str, shards: int) -> list[Path]:
    paths = [directory / f"pytest-output-{python}-{n}" / "pytest-report.xml"
             for n in range(1, shards + 1)]
    missing = [str(path.parent.name) for path in paths if not path.is_file()]
    if missing:
        raise ValueError("ci_shard_reports_missing: " + ", ".join(missing))
    return paths


def compare(expected: list[list[str]], reports: list[Path], python: str) -> dict:
    names = {(classname, name): nodeid for classname, name, nodeid in expected}
    if not names or len(names) != len(expected):
        raise ValueError("ci_shard_collection_invalid: empty or ambiguous collection")
    counts = Counter()
    for report in reports:
        cases = list(ET.parse(report).iter("testcase"))
        if not cases:
            raise ValueError(f"ci_shard_report_empty: {report}")
        for case in cases:
            key = (case.attrib.get("classname", ""), case.attrib["name"])
            if names.get(key, "").endswith(".py") and case.find("skipped") is None:
                raise ValueError(f"ci_shard_collection_skip_invalid: {names[key]} must report skipped")
            counts[key] += 1
    missing = sorted(names[key] for key in names if counts[key] == 0)
    duplicated = sorted(f"{names.get(key, '::'.join(key))} ({count} times)"
                        for key, count in counts.items() if count > 1)
    unexpected = sorted("::".join(key) for key in counts if key not in names)
    if missing or duplicated or unexpected:
        details = [f"ci_shard_coverage_mismatch: Python {python}"]
        for label, values in (("missing", missing), ("duplicated", duplicated),
                              ("unexpected", unexpected)):
            details.append(f"{label} ({len(values)}):")
            details.extend(values)
        raise ValueError("\n".join(details))
    return {"python": python, **collection_counts(expected), "reports": len(reports)}


def collection_counts(records) -> dict[str, int]:
    modules = sum(nodeid.endswith(".py") for _, _, nodeid in records)
    return {"tests": len(records) - modules, "collection_skips": modules}


def collect(destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    log = destination.parent / COLLECTION_LOG
    environment = dict(os.environ, **{MANIFEST_ENV: str(destination.resolve())})
    with log.open("w", encoding="utf-8") as output:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", *SUITE_PATHS, "--collect-only",
             "-q", "-n", "0", "-p", "yoke_core.tools.ci_shard_coverage"],
            env=environment, stdout=output, stderr=subprocess.STDOUT, check=False,
        )
    if result.returncode:
        raise ValueError(
            f"ci_shard_collection_failed: read {log} and repair collection "
            "before checking shard coverage"
        )


def _refuse(code: str, python: str, error: Exception, recovery: str) -> int:
    print(compose_refusal(f"{code}: Python {python}: {error}",
                          recovery=recovery))
    return 1


def load_manifest(path: Path) -> list[list[str]]:
    if not path.is_file():
        raise ValueError(
            f"ci_shard_collection_missing: {path} was not downloaded; read the "
            "shard-collection job for this Python leg, which owns the unsplit "
            "collection"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    collect_parser = commands.add_parser(
        "collect", help="Write the unsplit collection manifest.")
    collect_parser.add_argument("--python", required=True)
    collect_parser.add_argument("--output", type=Path, required=True)
    compare_parser = commands.add_parser(
        "compare", help="Replay a collection manifest against shard reports.")
    compare_parser.add_argument("--reports", type=Path, required=True)
    compare_parser.add_argument("--python", required=True)
    compare_parser.add_argument("--expected", type=Path, required=True)
    compare_parser.add_argument("--shards", type=int, default=SHARD_COUNT)
    args = parser.parse_args(argv)
    if args.command == "collect":
        try:
            collect(args.output)
            counts = collection_counts(load_manifest(args.output))
        except (OSError, ValueError) as error:
            return _refuse("ci_shard_collection_failed", args.python, error, recovery=(
                "read the collection log beside the manifest, repair collection on this commit, then verify it again"))
        print("ci_shard_collection_recorded: "
              + json.dumps({"python": args.python, **counts}))
        return 0
    try:
        paths = report_paths(args.reports, args.python, args.shards)
        result = compare(load_manifest(args.expected), paths, args.python)
    except (OSError, ValueError, KeyError, TypeError, ET.ParseError) as error:
        return _refuse("ci_shard_coverage_failed", args.python, error, recovery=(
            "download every shard report and the shard-collection manifest "
            "from this run, repair collection/profile divergence or missing "
            "test execution, then verify the corrected commit"))
    print("ci_shard_coverage_passed: " + json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
