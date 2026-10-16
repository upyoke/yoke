"""Transfer attested bytes from a successful main-push factory; never rebuild."""

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
from yoke_contracts.designed_wait import announce_designed_wait, poll_every


def run(command: list[str]) -> str:
    result = subprocess.run(
        command, check=True, text=True, capture_output=True, timeout=120
    )
    return result.stdout.strip()


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
        runs = json.loads(
            run(
                [
                    "gh",
                    "api",
                    f"repos/{repo}/actions/workflows/{workflow}/runs?head_sha={source}&branch=main&event=push&per_page=100",
                ]
            )
        )["workflow_runs"]
        eligible = [
            r
            for r in runs
            if r.get("head_sha") == source
            and r.get("head_branch") == "main"
            and r.get("event") == "push"
            and r.get("head_repository", {}).get("full_name", "").lower()
            == repo.lower()
        ]
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
    run(command)


def validate_wheels(root: Path, version: str, source: str) -> list[Path]:
    records = json.loads((root / "release-records.json").read_text())
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
    evidence = json.loads((root / "migration-history-record.json").read_text())[
        "artifact"
    ]
    if evidence["source_commit"] != source or evidence["engine_version"] != version:
        raise ValueError(
            "main_migration_identity_mismatch: rerun the main wheel factory"
        )
    return wheels


def promote(args) -> dict[str, str]:
    version = release_version(args.version)
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
    record = json.loads((args.destination / "image.json").read_text())
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
    parser.add_argument("kind", choices=("wheels", "image"))
    parser.add_argument("--repo", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--destination", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        result = promote(args)
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as out:
            out.writelines(f"{key}={value}\n" for key, value in result.items())
    except (
        ValueError,
        TypeError,
        KeyError,
        OSError,
        zipfile.BadZipFile,
        subprocess.SubprocessError,
    ) as exc:
        print(
            f"main_artifact_promotion_refused: {exc}; inspect the exact main factory and retry the failed publication job",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
