"""Read retained Actions evidence for server-image cache acceptance."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import re
import statistics
import subprocess


def _gh(*args: str) -> str:
    completed = subprocess.run(["gh", *args], text=True, capture_output=True)
    if completed.returncode:
        raise ValueError(
            "actions_evidence_unavailable: restore GitHub read access or retained run logs, then retry: "
            + completed.stderr.strip()
        )
    return completed.stdout


def build_seconds(jobs: list[dict]) -> float:
    """Use the slowest native build step as each run's image-build time."""
    durations = []
    for job in jobs:
        if not job["name"].startswith("build-native-"):
            continue
        step = next(
            step
            for step in job["steps"]
            if step["name"] == "Build and push the native content-addressed image"
        )
        if step["conclusion"] != "success":
            raise ValueError("image_build_incomplete: collect successful native builds")
        durations.append(
            (
                datetime.fromisoformat(step["completed_at"])
                - datetime.fromisoformat(step["started_at"])
            ).total_seconds()
        )
    if len(durations) != 2:
        raise ValueError(
            "native_build_evidence_missing: retain both architecture jobs and retry"
        )
    return max(durations)


def postgres_cached(log: str) -> bool:
    steps = re.findall(
        r"#(\d+) \[builder [^\]]+\] RUN PYTHONPATH=.*postgres_binaries.py", log
    )
    return any(re.search(rf"#{step} CACHED\b", log) for step in steps)


def application_changed_without_bootstrap(files: list[str]) -> bool:
    bootstrap = (
        "Dockerfile",
        "packages/yoke-contracts/src/",
        "packages/yoke-cli/src/",
        "packages/yoke-core/src/yoke_core/domain/postgres_binaries.py",
    )
    return any(
        name.startswith(("runtime/", "packages/yoke-core/src/")) for name in files
    ) and not any(name.startswith(bootstrap) for name in files)


def _check() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--baseline-run", action="append", required=True, type=int)
    args = parser.parse_args()
    if len(set(args.baseline_run)) != 10:
        parser.error(
            "baseline_sample_invalid: supply ten distinct pre-cache main run ids"
        )
    repository = args.repository
    runs = json.loads(
        _gh(
            "run",
            "list",
            "--repo",
            repository,
            "--workflow",
            "yoke-server-image.yml",
            "--branch",
            "main",
            "--event",
            "push",
            "--status",
            "success",
            "--limit",
            "100",
            "--json",
            "databaseId,headSha,url",
        )
    )
    current = []
    for run in runs:
        workflow = _gh(
            "api",
            f"repos/{repository}/contents/.github/workflows/yoke-server-image.yml?ref={run['headSha']}",
            "-H",
            "Accept: application/vnd.github.raw+json",
        )
        if "cache-to: type=gha,mode=max,scope=yoke-server-" in workflow:
            current.append(run)
        if len(current) == 10:
            break
    if len(current) != 10:
        print(
            f"cache_timing_sample_pending: found {len(current)}/10 successful cached main runs; wait for ten main image builds, then rerun this case"
        )
        return 1

    def measure(run_id: int) -> tuple[float, list[dict]]:
        jobs = json.loads(
            _gh("api", f"repos/{repository}/actions/runs/{run_id}/jobs?per_page=100")
        )["jobs"]
        return build_seconds(jobs), jobs

    try:
        baseline = [measure(run_id)[0] for run_id in args.baseline_run]
        timings, hits = [], []
        for index, run in enumerate(current):
            seconds, jobs = measure(run["databaseId"])
            timings.append(seconds)
            files = []
            if index + 1 < len(current):
                previous = current[index + 1]["headSha"]
                comparison = json.loads(
                    _gh(
                        "api",
                        f"repos/{repository}/compare/{previous}...{run['headSha']}",
                    )
                )
                files = [file["filename"] for file in comparison["files"]]
                if len(files) >= 300:
                    files = []  # The compare API truncates larger file sets.
            for job in jobs:
                if job["name"].startswith("build-native-"):
                    log = _gh(
                        "run",
                        "view",
                        str(run["databaseId"]),
                        "--repo",
                        repository,
                        "--log-job",
                        str(job["id"]),
                    )
                    if postgres_cached(log) and application_changed_without_bootstrap(
                        files
                    ):
                        hits.append(
                            {
                                "run": run["url"],
                                "job": job["name"],
                                "changed_files": files,
                            }
                        )
        improvement = statistics.median(baseline) - statistics.median(timings)
        print(
            json.dumps(
                {
                    "baseline_runs": args.baseline_run,
                    "baseline_seconds": baseline,
                    "cached_runs": current,
                    "cached_seconds": timings,
                    "median_improvement_seconds": improvement,
                    "postgres_cache_hits": hits,
                },
                indent=2,
            )
        )
        if {hit["job"] for hit in hits} != {"build-native-amd64", "build-native-arm64"}:
            raise ValueError(
                "postgres_source_change_cache_hit_missing: retain source changes without bootstrap edits and cache-hit logs for both architectures, then rerun"
            )
        if improvement < 30:
            raise ValueError(
                "image_cache_timing_target_missed: inspect build and cache transfer timings, fix the bottleneck, then collect ten new runs"
            )
    except (ValueError, StopIteration) as exc:
        print(
            str(exc)
            or "image_build_step_missing: retain native image-build step evidence and retry"
        )
        return 1
    return 0


def main() -> int:
    try:
        return _check()
    except (ValueError, KeyError, OSError) as exc:
        print(
            f"image_cache_evidence_unavailable: {exc}; restore complete retained Actions evidence and retry"
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
