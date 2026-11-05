# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from runtime.api.fixtures.machine_config_test import select_machine_config_file

import hashlib

import json

import sqlite3

import subprocess

import zipfile

from pathlib import Path

import pytest

from yoke_core.domain import db_backend, yoke_connected_env

from yoke_core.domain.migration_history_manifest import write_manifest

from yoke_core.tools import adopt_migration_content_identity as tool

from yoke_core.tools import github_artifact_attestation

from yoke_core.tools.migration_history_release_artifact import (
    manifest_for_core_wheel_path,
    write_release_evidence,
)

SOURCE_COMMIT = "b" * 40

SOURCE_REPOSITORY = "upyoke/yoke"

ADMIN_DSN = "host=selected.example user=admin dbname=yoke_stage"


def _legacy_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE applied_migrations ("
        "migration_name TEXT PRIMARY KEY, applied_at TEXT NOT NULL, "
        "applied_by TEXT, minimum_serving_version TEXT)"
    )
    conn.execute("CREATE TABLE marks (name TEXT)")
    conn.commit()
    return conn


def _artifact(tmp_path: Path) -> tuple[Path, Path, Path, str]:
    wheel = tmp_path / "yoke_core-1.2.3-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(
            "yoke_core-1.2.3.dist-info/METADATA",
            "Metadata-Version: 2.1\nName: yoke-core\nVersion: 1.2.3\n",
        )
        archive.writestr(
            "yoke_core-1.2.3.dist-info/WHEEL",
            "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        )
        archive.writestr(
            "yoke_core/domain/migrations/0001_existing.py",
            "def apply(conn):\n    pass\n\n"
            "def invariants(conn):\n"
            '    assert conn.execute("SELECT count(*) FROM marks")'
            ".fetchone()[0] == 0\n",
        )
    manifest = manifest_for_core_wheel_path(
        wheel,
        source_commit=SOURCE_COMMIT,
    )
    manifest_path = tmp_path / "migration-history.json"
    evidence_path = tmp_path / "migration-history-record.json"
    write_manifest(manifest_path, manifest)
    write_release_evidence(evidence_path, manifest)
    return wheel, manifest_path, evidence_path, manifest.content_sha256


def _argv(
    wheel: Path,
    manifest: Path,
    evidence: Path,
    manifest_sha256: str,
    *,
    mode: str,
    databases: tuple[str, ...] = ("yoke_test",),
) -> list[str]:
    args = [
        "stage-db-admin",
        *databases,
        "--wheel",
        str(wheel),
        "--manifest",
        str(manifest),
        "--release-evidence",
        str(evidence),
        "--repository",
        SOURCE_REPOSITORY,
        "--source-commit",
        SOURCE_COMMIT,
        "--manifest-sha256",
        manifest_sha256,
        "--adopted-by",
        "operator:test",
    ]
    if mode != "verify":
        args.append(f"--{mode}")
    return args


def _mock_github_attestations(
    monkeypatch: pytest.MonkeyPatch,
    *,
    returncode: int = 0,
    digest_overrides: dict[str, str] | None = None,
) -> list[tuple[str, ...]]:
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        github_artifact_attestation,
        "_resolve_executable",
        lambda _executable: "/usr/bin/gh",
    )

    def run(command):
        captured = tuple(command)
        calls.append(captured)
        path = Path(captured[3])
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest_overrides and path.name in digest_overrides:
            digest = digest_overrides[path.name]
        payload = [
            {
                "verificationResult": {
                    "statement": {
                        "subject": [{"name": path.name, "digest": {"sha256": digest}}]
                    }
                }
            }
        ]
        return subprocess.CompletedProcess(
            list(command),
            returncode,
            stdout=json.dumps(payload),
            stderr="external verifier diagnostic",
        )

    monkeypatch.setattr(github_artifact_attestation, "_run_verification", run)
    return calls


def _mock_admin_authority(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tool, "_admin_authority_dsn", lambda _environment: ADMIN_DSN)
