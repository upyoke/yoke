"""Promote attested main-push artifacts and recover stale runs in hosted CI."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import zipfile
from email.parser import BytesParser

from yoke_contracts.release_version import release_version
from yoke_contracts.timestamps import parse_instant
from yoke_contracts.designed_wait import announce_designed_wait, poll_every


def run(command: list[str], *, timeout: float = 120) -> str:
    result = subprocess.run(
        command, check=True, text=True, capture_output=True, timeout=timeout
    )
    return result.stdout.strip()


def _eligible_runs(repo: str, workflow: str, sha: str, ref: str) -> list[dict]:
    runs = json.loads(run([
        "gh", "api",
        f"repos/{repo}/actions/workflows/{workflow}/runs?head_sha={sha}&event=push&per_page=100",
    ]))["workflow_runs"]
    return [
        r for r in runs
        if r.get("head_sha") == sha
        and r.get("head_branch") == ref
        and r.get("event") == "push"
        and (r.get("head_repository") or {}).get("full_name", "").lower() == repo.lower()
    ]


def latest_run(repo: str, workflow: str, sha: str, ref: str) -> dict | None:
    """Read the newest exact push run, or leave the existing verdict alone."""
    try:
        return max(_eligible_runs(repo, workflow, sha, ref), key=lambda r: r["id"], default=None)
    except (ValueError, TypeError, KeyError, AttributeError, OSError, subprocess.SubprocessError):
        return None


def stale_failure(run: dict | None, upstream: dict | None) -> bool:
    if not run or run.get("status") != "completed" or run.get("conclusion") != "failure":
        return False
    if not upstream or upstream.get("status") != "completed" or upstream.get("conclusion") != "success":
        return False
    try:
        return parse_instant(run.get("updated_at")) < parse_instant(upstream.get("updated_at"))
    except ValueError:
        return False


def _wait_for_attempt(repo: str, run_id: str, attempt: int) -> None:
    deadline = time.monotonic() + 30
    while (remaining := deadline - time.monotonic()) > 0:
        current = json.loads(run(
            ["gh", "api", f"repos/{repo}/actions/runs/{run_id}"], timeout=remaining
        ))
        if current["run_attempt"] > attempt or current["status"] != "completed":
            return
        time.sleep(min(2, max(0, deadline - time.monotonic())))
    raise ValueError(
        f"factory_rerun_not_visible: inspect {repo} run {run_id} and retry the release bridge"
    )


def rerun_stale(repo: str, sha: str, tag: str) -> int:
    wheels, image = "yoke-build-artifacts.yml", "yoke-server-image.yml"
    for workflow, ref, upstream_workflow in (
        (image, "main", wheels),
        ("yoke-release.yml", tag, wheels),
        (image, tag, image),
    ):
        candidate = latest_run(repo, workflow, sha, ref)
        upstream = latest_run(repo, upstream_workflow, sha, "main")
        if not candidate or not stale_failure(candidate, upstream):
            continue
        run_id = str(candidate["id"])
        print(f"Rerunning stale {workflow} ({ref}) run {run_id}", flush=True)
        command = ["gh", "run", "rerun", run_id, "--failed", "--repo", repo]
        try:
            run(command)
        except subprocess.CalledProcessError as exc:
            raise ValueError(f"factory_rerun_refused: {exc.stderr or exc.stdout or exc}") from exc
        _wait_for_attempt(repo, run_id, candidate["run_attempt"])
        result = subprocess.run([
            "yoke", "github-actions", "wait-run", repo, run_id,
            "--project", "yoke", "--timeout", "3600",
        ])
        if result.returncode == 3:
            print(f"{workflow} run {run_id} is still in flight", flush=True)
            return 0
        if result.returncode:
            raise ValueError(
                f"factory_failed: {workflow} run {run_id} wait exited {result.returncode}"
            )
    return 0


def successful_main_run(repo: str, workflow: str, source: str) -> int:
    """Admit only a successful push on main at the exact candidate commit."""
    if not re.fullmatch(r"[0-9a-f]{40}", source):
        raise ValueError(
            "main_artifact_source_invalid: pass a full lowercase commit SHA"
        )
    deadline = time.monotonic() + 300
    announce_designed_wait(
        f"exact main factory {workflow} for {source}",
        max_wait_seconds=300,
        cadence=poll_every(5),
    )
    while True:
        eligible = _eligible_runs(repo, workflow, source, "main")
        passed = [
            r
            for r in eligible
            if r.get("status") == "completed" and r.get("conclusion") == "success"
        ]
        if passed:
            return int(max(passed, key=lambda r: r["id"])["id"])
        if eligible and all(r.get("status") == "completed" for r in eligible):
            raise ValueError(
                f"main_factory_failed: inspect and rerun {workflow} for {source}; tag publication does not rebuild"
            )
        if time.monotonic() >= deadline:
            raise ValueError(
                f"main_factory_unavailable: run {workflow} on a push to main at {source}, then retry publication"
            )
        time.sleep(5)


def download(
    repo: str, workflow: str, source: str, name: str, destination: Path
) -> int:
    run_id = successful_main_run(repo, workflow, source)
    run(
        [
            "gh",
            "run",
            "download",
            str(run_id),
            "--repo",
            repo,
            "--name",
            name,
            "--dir",
            str(destination),
        ]
    )
    print(f"Reused main factory: https://github.com/{repo}/actions/runs/{run_id}")
    return run_id


def attest(
    subject: str, repo: str, source: str, workflow: str, *, oci: bool = False
) -> None:
    command = [
        "gh",
        "attestation",
        "verify",
        subject,
        "--repo",
        repo,
        "--signer-workflow",
        f"{repo}/.github/workflows/{workflow}",
        "--source-ref",
        "refs/heads/main",
        "--source-digest",
        source,
        "--deny-self-hosted-runners",
    ]
    if oci:
        command.append("--bundle-from-oci")
    output = run(command)
    print(f"Attestation verified: {subject}\n{output}", flush=True)


def validate_wheels(root: Path, version: str, source: str) -> list[Path]:
    records = json.loads((root / "release-records.json").read_text(encoding="utf-8"))
    expected = {r["filename"] for r in records}
    wheels = sorted((root / "wheels").glob("*.whl"))
    if (
        len(records) != 4
        or {r["name"] for r in records}
        != {"yoke-contracts", "yoke-cli", "yoke-harness", "yoke-core"}
        or len(expected) != len(records)
        or {p.name for p in wheels} != expected
    ):
        raise ValueError(
            "main_wheel_set_mismatch: rerun the main wheel factory and retry publication"
        )
    for record in records:
        if Path(record["filename"]).name != record["filename"]:
            raise ValueError("main_wheel_path_invalid: rerun the main wheel factory")
        path = root / "wheels" / record["filename"]
        content = path.read_bytes()
        if (
            record["version"] != version
            or len(content) != record["size"]
            or hashlib.sha256(content).hexdigest() != record["sha256"]
        ):
            raise ValueError(
                f"main_wheel_identity_mismatch: rebuild the main artifact for {source}"
            )
        with zipfile.ZipFile(path) as wheel:
            metadata_paths = [
                n for n in wheel.namelist() if n.endswith(".dist-info/METADATA")
            ]
            if len(metadata_paths) != 1 or wheel.testzip() is not None:
                raise ValueError("main_wheel_invalid: rerun the main factory")
            metadata = BytesParser().parsebytes(wheel.read(metadata_paths[0]))
            if metadata["Version"] != version or metadata["Name"] != record["name"]:
                raise ValueError("main_wheel_metadata_mismatch: rerun the main factory")
    evidence = json.loads((root / "migration-history-record.json").read_text(encoding="utf-8"))[
        "artifact"
    ]
    if evidence["source_commit"] != source or evidence["engine_version"] != version:
        raise ValueError(
            "main_migration_identity_mismatch: rerun the main wheel factory"
        )
    return wheels


def promote(args) -> dict[str, str]:
    version = release_version(args.version)
    if args.kind == "check-wheels":
        validate_wheels(args.destination, version, args.source_sha)
        return {"release_version": version}
    if args.kind == "wheels":
        workflow = "yoke-build-artifacts.yml"
        name = f"yoke-release-{args.source_sha}"
        download(args.repo, workflow, args.source_sha, name, args.destination)
        subjects = validate_wheels(args.destination, version, args.source_sha)
        subjects += [
            args.destination / "migration-history.json",
            args.destination / "migration-history-record.json",
        ]
        for path in subjects:
            attest(str(path), args.repo, args.source_sha, workflow)
        return {"release_version": version}
    workflow = "yoke-server-image.yml"
    download(
        args.repo,
        workflow,
        args.source_sha,
        f"yoke-image-{args.source_sha}",
        args.destination,
    )
    record = json.loads((args.destination / "image.json").read_text(encoding="utf-8"))
    repository = f"ghcr.io/{args.repo.split('/')[0].lower()}/yoke-server"
    if (
        record["source_sha"] != args.source_sha
        or record["release_version"] != version
        or record["repository"] != repository
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", record["digest"])
    ):
        raise ValueError(
            "main_image_identity_mismatch: rerun the exact main image factory"
        )
    attest(
        f"oci://{repository}@{record['digest']}",
        args.repo,
        args.source_sha,
        workflow,
        oci=True,
    )
    return record


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=("wheels", "image", "check-wheels", "rerun-stale"))
    parser.add_argument("--repo")
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--version")
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--tag")
    args = parser.parse_args(argv)
    if args.kind != "check-wheels" and not args.repo:
        parser.error("--repo is required for promotion")
    if args.kind == "rerun-stale":
        if not args.tag:
            parser.error("--tag is required for rerun-stale")
    elif not args.version or args.destination is None:
        parser.error("--version and --destination are required for artifact validation")
    try:
        if args.kind == "rerun-stale":
            return rerun_stale(args.repo, args.source_sha, args.tag)
        result = promote(args)
        if args.kind != "check-wheels":
            with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8", newline="\n") as out:
                out.writelines(f"{key}={value}\n" for key, value in result.items())
        print(f"Main artifact validation passed: {args.kind} {args.source_sha}")
    except (
        ValueError,
        TypeError,
        KeyError,
        OSError,
        zipfile.BadZipFile,
        subprocess.SubprocessError,
    ) as exc:
        print(
            f"::error::main_artifact_promotion_refused: {exc}; inspect the exact main factory and retry the failed publication job",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
