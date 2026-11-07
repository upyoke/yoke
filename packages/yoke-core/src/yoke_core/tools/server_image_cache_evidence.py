"""Read retained Actions evidence for server-image cache acceptance."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import re
import statistics
import base64

import os
import subprocess

from yoke_core.domain.github_actions_rest import rest_get, RestTransportError
from yoke_core.domain.github_actions_logs import fetch_job_log


def github_token(repository: str) -> str:
    """Read the configured Git helper without exposing its credential output."""
    result = subprocess.run(
        ["git", "credential", "fill"],
        input=f"protocol=https\nhost=github.com\npath={repository}\n\n",
        text=True,
        capture_output=True,
        timeout=30,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "false"},
    )
    fields = dict(
        line.split("=", 1) for line in result.stdout.splitlines() if "=" in line
    )
    if result.returncode or not fields.get("password"):
        raise ValueError(
            "github_read_auth_unavailable: run `yoke github status` and repair the configured Git credential helper, then retry"
        )
    return fields["password"]


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
        r"#(\d+) \[(?:builder|runtime-base) [^\]]+\] RUN .*PYTHONPATH=.*postgres_binaries.py",
        log,
    )
    return any(re.search(rf"#{step} CACHED\b", log) for step in steps)


def buildkit_timings(log: str) -> list[dict]:
    """Keep completed vertex durations for diagnosing transfer/build overhead."""
    names, timings = {}, []
    for match in re.finditer(r"#(\d+) ([^\r\n]+)", log):
        vertex, message = match.groups()
        if vertex == "0" and message.startswith("building with "):
            names.clear()  # Job logs can also contain Buildx setup vertices.
        done = re.fullmatch(r"DONE ([\d.]+)s", message)
        if done and vertex in names:
            timings.append({"step": names[vertex], "seconds": float(done[1])})
        elif vertex not in names and not re.match(r"[\d.]+ |CACHED$", message):
            names[vertex] = message
    return sorted(timings, key=lambda row: row["seconds"], reverse=True)


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
    parser.add_argument(
        "--diagnostics",
        action="store_true",
        help="Include retained BuildKit vertex timings for both sample groups",
    )
    args = parser.parse_args()
    if len(set(args.baseline_run)) != 10:
        parser.error(
            "baseline_sample_invalid: supply ten distinct pre-cache main run ids"
        )
    repository = args.repository
    token = github_token(repository)
    runs = rest_get(
        f"/repos/{repository}/actions/workflows/yoke-server-image.yml/runs",
        query={
            "branch": "main",
            "event": "push",
            "status": "success",
            "per_page": "100",
        },
        token=token,
    )["workflow_runs"]
    current = []
    for run in runs:
        source = rest_get(
            f"/repos/{repository}/contents/.github/workflows/yoke-server-image.yml",
            query={"ref": run["head_sha"]},
            token=token,
        )
        workflow = base64.b64decode(source["content"]).decode()
        if (
            "cache-to: type=registry,ref=${{ needs.validate-tag.outputs.repository }}:buildcache-builder-${{ matrix.arch }},mode=max"
            in workflow
        ):
            current.append(
                {
                    "databaseId": run["id"],
                    "headSha": run["head_sha"],
                    "url": run["html_url"],
                }
            )
        if len(current) == 10:
            break
    if len(current) != 10:
        print(
            f"cache_timing_sample_pending: found {len(current)}/10 successful cached main runs; wait for ten main image builds, then rerun this case"
        )
        return 1

    def measure(run_id: int) -> tuple[float, list[dict]]:
        jobs = rest_get(
            f"/repos/{repository}/actions/runs/{run_id}/jobs",
            query={"per_page": "100"},
            token=token,
        )["jobs"]
        return build_seconds(jobs), jobs

    try:
        diagnostics = []

        def diagnose(run_id, jobs):
            for job in jobs:
                if job["name"].startswith("build-native-"):
                    log = fetch_job_log(repository, job["id"], token=token)
                    diagnostics.append(
                        {
                            "run_id": run_id,
                            "job": job["name"],
                            "vertices": buildkit_timings(log),
                        }
                    )

        baseline = []
        for run_id in args.baseline_run:
            seconds, jobs = measure(run_id)
            baseline.append(seconds)
            if args.diagnostics:
                diagnose(run_id, jobs)
        timings, hits = [], []
        for index, run in enumerate(current):
            seconds, jobs = measure(run["databaseId"])
            timings.append(seconds)
            files = []
            if index + 1 < len(current):
                previous = current[index + 1]["headSha"]
                comparison = rest_get(
                    f"/repos/{repository}/compare/{previous}...{run['headSha']}",
                    token=token,
                )
                files = [file["filename"] for file in comparison["files"]]
                if len(files) >= 300:
                    files = []  # The compare API truncates larger file sets.
            for job in jobs:
                if job["name"].startswith("build-native-"):
                    log = fetch_job_log(repository, job["id"], token=token)
                    if args.diagnostics:
                        diagnostics.append(
                            {
                                "run_id": run["databaseId"],
                                "job": job["name"],
                                "vertices": buildkit_timings(log),
                            }
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
                    **({"buildkit_timings": diagnostics} if args.diagnostics else {}),
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
    except (
        ValueError,
        KeyError,
        TypeError,
        OSError,
        subprocess.TimeoutExpired,
        RestTransportError,
    ) as exc:
        print(
            f"image_cache_evidence_unavailable: {exc}; run `yoke github status` to check saved GitHub access, restore complete retained Actions evidence, and retry"
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
