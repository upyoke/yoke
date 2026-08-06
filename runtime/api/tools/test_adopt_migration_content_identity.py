"""Installed admin adoption surface binds release evidence before writes."""

from __future__ import annotations

import sqlite3
import zipfile
from pathlib import Path

import pytest

from yoke_core.domain.migration_history_manifest import write_manifest
from yoke_core.tools import adopt_migration_content_identity as tool
from yoke_core.tools.migration_history_release_artifact import (
    manifest_for_core_wheel_path,
    write_release_evidence,
)


SOURCE_COMMIT = "b" * 40


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
) -> list[str]:
    args = [
        "stage-db-admin",
        "yoke_test",
        "--wheel",
        str(wheel),
        "--manifest",
        str(manifest),
        "--release-evidence",
        str(evidence),
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


def test_admin_surface_verifies_then_explicitly_applies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    wheel, manifest, evidence, digest = _artifact(tmp_path)
    conn = _legacy_connection()
    conn.execute(
        "INSERT INTO applied_migrations "
        "(migration_name, applied_at, applied_by) "
        "VALUES ('0001_existing', 'now', 'legacy')"
    )
    conn.commit()
    monkeypatch.setattr(tool, "_connect_database", lambda _database: conn)

    assert tool.main(_argv(wheel, manifest, evidence, digest, mode="verify")) == 1
    assert (
        conn.execute(
            "SELECT count(*) FROM sqlite_master "
            "WHERE type='table' AND name='migration_content_adoptions'"
        ).fetchone()[0]
        == 0
    )

    assert tool.main(_argv(wheel, manifest, evidence, digest, mode="prepare")) == 0
    assert "additive digest/evidence schema committed" in capsys.readouterr().out
    assert (
        conn.execute("SELECT content_sha256 FROM applied_migrations").fetchone()[0]
        is None
    )

    assert tool.main(_argv(wheel, manifest, evidence, digest, mode="verify")) == 0
    assert (
        conn.execute("SELECT content_sha256 FROM applied_migrations").fetchone()[0]
        is None
    )

    assert tool.main(_argv(wheel, manifest, evidence, digest, mode="apply")) == 0
    assert (
        conn.execute("SELECT content_sha256 FROM applied_migrations").fetchone()[0]
        is not None
    )
    row = conn.execute(
        "SELECT source_commit, manifest_sha256 FROM migration_content_adoptions"
    ).fetchone()
    assert row == (SOURCE_COMMIT, digest)


def test_admin_surface_rejects_external_evidence_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wheel, manifest, evidence, digest = _artifact(tmp_path)
    conn = _legacy_connection()
    conn.execute(
        "INSERT INTO applied_migrations "
        "(migration_name, applied_at, applied_by) "
        "VALUES ('0001_existing', 'now', 'legacy')"
    )
    conn.commit()
    monkeypatch.setattr(tool, "_connect_database", lambda _database: conn)

    assert tool.main(_argv(wheel, manifest, evidence, digest, mode="prepare")) == 0
    assert tool.main(_argv(wheel, manifest, evidence, "f" * 64, mode="apply")) == 1
    assert (
        conn.execute("SELECT content_sha256 FROM applied_migrations").fetchone()[0]
        is None
    )
