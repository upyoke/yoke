"""Summarize retained GitHub metadata and complete JUnit artifacts without reruns."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET

from yoke_core.tools.ci_durations_refresh import node_id


def seconds(start: str, end: str) -> float:
    return (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()


def job_metrics(job: dict) -> dict:
    start, end = job["started_at"], job["completed_at"]
    pytest_steps = [s for s in job["steps"] if s["name"] == "Run pytest"]
    test = pytest_steps[0] if pytest_steps else None
    return {
        "name": job["name"], "conclusion": job["conclusion"],
        "queue_seconds": seconds(job["created_at"], start),
        "setup_seconds": seconds(start, test["started_at"]) if test else None,
        "test_seconds": seconds(test["started_at"], test["completed_at"]) if test else None,
        "total_seconds": seconds(start, end),
        "runner_labels": job["labels"],
    }


def peak_concurrency(jobs: list[dict]) -> int:
    events = sorted(
        (stamp, delta)
        for job in jobs
        for stamp, delta in ((job["started_at"], 1), (job["completed_at"], -1))
    )
    current = peak = 0
    for _stamp, delta in events:
        current += delta
        peak = max(peak, current)
    return peak


def endpoint_metrics(root: Path, reports: Path, python: str, shards: int) -> dict:
    files: Counter = Counter()
    cases = []
    counts: Counter = Counter()
    seen = set()
    walls = []
    capacities = []
    for shard in range(1, shards + 1):
        directory = reports / f"pytest-output-{python}-{shard}"
        document = ET.parse(directory / "pytest-report.xml")
        suites = list(document.iter("testsuite"))
        if any(int(s.get("failures", 0)) or int(s.get("errors", 0)) for s in suites):
            raise ValueError("failed JUnit report cannot prove complete passing coverage")
        walls.append(sum(float(s.attrib["time"]) for s in suites))
        for case in document.iter("testcase"):
            key = node_id(root, case) or f"{case.get('classname')}::{case.get('name')}"
            if key in seen:
                raise ValueError(f"duplicate case on Python {python}: {key}")
            seen.add(key)
            duration = float(case.get("time", 0))
            counts["cases"] += 1
            counts["skipped" if case.find("skipped") is not None else "passed"] += 1
            files[key.split("::", 1)[0]] += duration
            cases.append({"node_id": key, "seconds": duration})
        for line in (directory / "pytest-output.txt").read_text().splitlines():
            marker = "CI runner capacity: "
            if marker in line:
                capacities.append(json.loads(line.split(marker, 1)[1]))
                break
    return {
        **counts, "shards": shards, "suite_wall_seconds": walls,
        "aggregate_case_seconds": sum(files.values()),
        "slowest_files": [{"file": name, "seconds": value} for name, value in files.most_common(25)],
        "slowest_cases": sorted(cases, key=lambda c: c["seconds"], reverse=True)[:25],
        "runner_capacity": capacities,
    }


def report(root: Path, run: dict, jobs: list[dict], coverage: dict, reports: Path) -> dict:
    if run["status"] != "completed" or run["conclusion"] != "success":
        raise ValueError("use a completed successful run; an active run is not timing evidence")
    if coverage["run_id"] != run["id"]:
        raise ValueError("coverage artifact belongs to a different run")
    if any(job["status"] != "completed" for job in jobs):
        raise ValueError("job metadata is incomplete")
    metrics = [job_metrics(job) for job in jobs if job["conclusion"] != "skipped"]
    endpoints = {
        python: endpoint_metrics(root, reports, python, coverage["coverage"]["shards"])
        for python in coverage["coverage"]["python"]
    }
    return {
        "run_url": run["html_url"], "run_id": run["id"],
        "head_commit": run["head_sha"], "tested_commit": coverage["commit"],
        "tested_tree": coverage["tree"], "executed_full_suite": True,
        "workflow_seconds": seconds(run["created_at"], max(j["completed_at"] for j in jobs)),
        "runner_minutes": sum(j["total_seconds"] for j in metrics) / 60,
        "rounded_runner_minutes_estimate": sum(math.ceil(j["total_seconds"] / 60) for j in metrics),
        "billing_note": "Runner consumption estimate, not an invoice; excludes queue time and account discounts.",
        "peak_observed_job_concurrency": peak_concurrency(jobs),
        "jobs": metrics, "endpoints": endpoints,
        "measurement_note": "JUnit case sums include concurrent work and setup attribution; they are not elapsed workflow time.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("run", "jobs", "coverage", "reports", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    try:
        result = report(
            args.root, json.loads(args.run.read_text()),
            json.loads(args.jobs.read_text())["jobs"],
            json.loads(args.coverage.read_text()), args.reports,
        )
    except (OSError, ValueError, KeyError, ET.ParseError) as exc:
        parser.exit(1, f"ci_timing_evidence_invalid: {exc}; download matching complete run artifacts and retry\n")
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(f"CI timing report: {args.output}; elapsed {result['workflow_seconds']:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
