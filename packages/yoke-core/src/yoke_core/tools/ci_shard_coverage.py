"""Prove that every selected test ran exactly once across one Python leg."""

from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

from yoke_core.tools.ci_shards import SHARD_COUNT, SUITE_PATHS

MANIFEST_ENV = "YOKE_CI_COLLECTION_MANIFEST"


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
        counts.update((case.attrib.get("classname", ""), case.attrib["name"])
                      for case in cases)
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
    return {"python": python, "tests": len(names), "reports": len(reports)}


def collect(destination: Path) -> None:
    environment = dict(os.environ, **{MANIFEST_ENV: str(destination.resolve())})
    with Path("collection-output.txt").open("w", encoding="utf-8") as output:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", *SUITE_PATHS, "--collect-only",
             "-q", "-n", "0", "-p", "yoke_core.tools.ci_shard_coverage"],
            env=environment, stdout=output, stderr=subprocess.STDOUT, check=False,
        )
    if result.returncode:
        raise ValueError(
            "ci_shard_collection_failed: read collection-output.txt and repair "
            "collection before checking shard coverage"
        )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reports", type=Path, required=True)
    parser.add_argument("--python", required=True)
    parser.add_argument("--shards", type=int, default=SHARD_COUNT)
    parser.add_argument("--expected", type=Path,
                        help="Replay a saved unsplit collection instead of collecting.")
    args = parser.parse_args(argv)
    try:
        paths = report_paths(args.reports, args.python, args.shards)
        manifest = args.expected or Path("expected-tests.json")
        if args.expected is None:
            collect(manifest)
        result = compare(json.loads(manifest.read_text(encoding="utf-8")),
                         paths, args.python)
    except (OSError, ValueError, KeyError, TypeError, ET.ParseError) as error:
        print(f"ci_shard_coverage_failed: Python {args.python}: {error}\nRecovery: download every shard report from this run, "
              "repair collection/profile divergence or missing test execution, "
              "then verify the corrected commit.")
        return 1
    print("ci_shard_coverage_passed: " + json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
