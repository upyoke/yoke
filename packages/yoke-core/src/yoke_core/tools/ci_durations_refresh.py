"""Refresh shard weights from one complete newest-Python CI report set."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import xml.etree.ElementTree as ET

from yoke_core.tools.ci_shards import DURATIONS_PATH, SHARD_COUNT


def node_id(root: Path, case: ET.Element) -> str | None:
    parts = case.attrib.get("classname", "").split(".")
    for end in range(len(parts), 0, -1):
        filename = "/".join(parts[:end]) + ".py"
        if (root / filename).is_file():
            return "::".join([filename, *parts[end:], case.attrib["name"]])
    return None  # A report from a prior tree can include tests since deleted.


def refresh(root: Path, reports: list[Path], *, expected_shards=SHARD_COUNT, reset=False) -> dict:
    if len(reports) != expected_shards:
        raise ValueError(
            f"ci_profile_incomplete: expected {expected_shards} reports, got "
            f"{len(reports)}; download every newest-Python shard from one successful run."
        )
    profile = {}
    walls = []
    for report in reports:
        document = ET.parse(report)
        suites = list(document.iter("testsuite"))
        if any(
            int(s.attrib.get("failures", 0)) or int(s.attrib.get("errors", 0))
            for s in suites
        ):
            raise ValueError(
                "ci_profile_failed_run: use reports from a successful run."
            )
        wall = sum(float(s.attrib["time"]) for s in suites)
        cases = list(document.iter("testcase"))
        measured = sum(float(c.attrib.get("time", 0)) for c in cases)
        if measured <= 0 or wall <= 0:
            raise ValueError(
                "ci_profile_empty: use completed reports with measured times."
            )
        walls.append(wall)
        for case in cases:
            key = node_id(root, case)
            if key is None:
                continue
            if key in profile:
                raise ValueError(
                    f"ci_profile_duplicate: {key}; use one interpreter's reports "
                    "from one run, with each shard included once."
                )
            profile[key] = round(
                max(float(case.attrib.get("time", 0)), 0.001) * wall / measured, 6
            )
    if not profile:
        raise ValueError(
            "ci_profile_no_current_tests: use reports matching this checkout."
        )
    destination = root / DURATIONS_PATH
    try:
        previous = json.loads(destination.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        previous = {}
    if reset:
        previous = {}
    # Shared fixture setup moves between cases/files and runner contention
    # varies. Damp that noise instead of reversing the allocation each run.
    profile = {
        key: round((value + float(previous.get(key, value))) / 2, 6)
        for key, value in profile.items()
    }
    temporary = destination.with_suffix(".refresh")
    temporary.write_text(
        json.dumps(profile, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(destination)
    return {"profiled_tests": len(profile), "shard_wall_seconds": walls}


def _gh(arguments):
    result = subprocess.run(
        ["gh", *arguments], check=True, capture_output=True, text=True, timeout=120
    )
    return json.loads(result.stdout)


def profile_baseline(root: Path) -> str:
    """The committed cost reset that an automatic measurement must include."""
    result = subprocess.run(
        ["git", "-C", str(root), "log", "-1", "--format=%H", "--", DURATIONS_PATH],
        capture_output=True, text=True, timeout=30,
    )
    commit = result.stdout.strip()
    if result.returncode or not commit:
        raise ValueError(
            "ci_profile_baseline_missing: commit the timing profile before "
            "automatic refresh, or use --reports from a verified full run."
        )
    return commit


def contains_baseline(root: Path, baseline: str, commit: str) -> bool:
    result = subprocess.run(
        ["git", "-C", str(root), "merge-base", "--is-ancestor", baseline, commit],
        capture_output=True, text=True, timeout=30,
    )
    # A missing revision cannot establish that the source includes the reset.
    return result.returncode == 0


def download_latest(root: Path, repository: str, python: str, directory: Path) -> str:
    """Read existing CI artifacts; no scheduler, commit, or credential mutation."""
    baseline = profile_baseline(root)
    runs = _gh(
        [
            "run",
            "list",
            "--repo",
            repository,
            "--workflow",
            "yoke-ci.yml",
            "--status",
            "success",
            "--limit",
            "50",
            "--json",
            "databaseId,headSha",
        ]
    )
    names = {f"pytest-output-{python}-{group}" for group in range(1, SHARD_COUNT + 1)}
    for run in runs:
        if not contains_baseline(root, baseline, run.get("headSha", "")):
            continue
        run_id = str(run["databaseId"])
        pages = _gh([
            "api", "--paginate", "--slurp",
            f"repos/{repository}/actions/runs/{run_id}/artifacts",
        ])
        available = {
            a["name"] for page in pages for a in page["artifacts"]
            if not a["expired"] and a["name"].startswith(f"pytest-output-{python}-")
        }
        if names != available:
            continue
        subprocess.run(
            [
                "gh",
                "run",
                "download",
                run_id,
                "--repo",
                repository,
                "--pattern",
                f"pytest-output-{python}-*",
                "--dir",
                str(directory),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
        return run_id
    raise ValueError(
        "ci_profile_reports_unavailable: no complete retained CI report set "
        "whose source contains the committed timing baseline; retain that "
        "baseline and refresh from a passing descendant run, or use --reports "
        "from a verified full run after changing fixture costs."
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-root", type=Path, required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--reports", type=Path)
    source.add_argument("--latest", action="store_true")
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY"))
    parser.add_argument("--python", default="3.14")
    parser.add_argument(
        "--reset", action="store_true",
        help="Replace prior weights when fixture setup or scheduling costs changed.",
    )
    args = parser.parse_args(argv)
    from yoke_core.domain.workspace_authority import (
        assert_target_under_session_work_authority,
    )

    try:
        assert_target_under_session_work_authority(args.target_root / DURATIONS_PATH)
        with tempfile.TemporaryDirectory(prefix="yoke-ci-profile-") as temporary:
            directory = args.reports
            run_id = None
            if args.latest:
                if not args.repository:
                    raise ValueError(
                        "ci_profile_repository_required: pass --repository owner/repo."
                    )
                directory = Path(temporary)
                run_id = download_latest(
                    args.target_root, args.repository, args.python, directory
                )
            result = refresh(
                args.target_root, sorted(directory.rglob("pytest-report.xml")),
                reset=args.reset,
            )
            print(json.dumps({"source_run_id": run_id, **result}))
        return 0
    except (
        OSError,
        ValueError,
        RuntimeError,
        ET.ParseError,
        subprocess.SubprocessError,
    ) as error:
        print(
            f"ci_profile_refresh_failed: {error}; retain the committed profile "
            "and retry with --reports from one successful full run."
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
