"""Installed admin adoption surface binds release evidence before writes."""

from __future__ import annotations

from runtime.api.tools.adopt_migration_content_identity_test_support import (
    ADMIN_DSN as ADMIN_DSN,
    SOURCE_COMMIT as SOURCE_COMMIT,
    SOURCE_REPOSITORY as SOURCE_REPOSITORY,
    _argv as _argv,
    _artifact as _artifact,
    _legacy_connection as _legacy_connection,
    _mock_admin_authority as _mock_admin_authority,
    _mock_github_attestations as _mock_github_attestations,
)


from runtime.api.fixtures.machine_config_test import select_machine_config_file
import json
from pathlib import Path

import pytest

from yoke_core.domain import db_backend, yoke_connected_env
from yoke_core.tools import adopt_migration_content_identity as tool
from yoke_core.tools import github_artifact_attestation


def _mock_database_connection(monkeypatch, conn) -> None:
    monkeypatch.setattr(tool, "_connect_database", lambda _database, **_kwargs: conn)


def test_selected_admin_authority_does_not_fall_through_to_ambient_dsn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dsn_file = tmp_path / "stage-admin.dsn"
    dsn_file.write_text(ADMIN_DSN, encoding="utf-8")
    binding = tmp_path / "config.json"
    binding.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "active_env": "stage-db-admin",
                "connections": {
                    "stage-db-admin": {
                        "transport": "local-postgres",
                        "credential_source": {
                            "kind": "dsn_file",
                            "path": str(dsn_file),
                        },
                    }
                },
                "projects": [],
            }
        ),
        encoding="utf-8",
    )
    select_machine_config_file(monkeypatch, binding)
    monkeypatch.setenv(yoke_connected_env.PYTEST_ENABLE_ENV, "1")
    monkeypatch.setenv(db_backend.PG_DSN_ENV, "host=ambient.example dbname=wrong")
    seen: list[str] = []
    sentinel = object()
    monkeypatch.setattr(
        db_backend,
        "connect_psycopg",
        lambda dsn: (seen.append(dsn), sentinel)[1],
    )

    authority = tool._admin_authority_dsn("stage-db-admin")
    assert tool._connect_database("yoke_tenant", authority_dsn=authority) is sentinel
    assert len(seen) == 1
    from psycopg import conninfo

    selected = conninfo.conninfo_to_dict(seen[0])
    assert selected["host"] == "selected.example"
    assert selected["dbname"] == "yoke_tenant"


def test_admin_surface_verifies_then_explicitly_applies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    wheel, manifest, evidence, digest = _artifact(tmp_path)
    verification_calls = _mock_github_attestations(monkeypatch)
    _mock_admin_authority(monkeypatch)
    conn = _legacy_connection()
    conn.execute(
        "INSERT INTO applied_migrations "
        "(migration_name, applied_at, applied_by) "
        "VALUES ('0001_existing', 'now', 'legacy')"
    )
    conn.commit()
    _mock_database_connection(monkeypatch, conn)

    assert tool.main(_argv(wheel, manifest, evidence, digest, mode="verify")) == 1
    assert (
        conn.execute(
            "SELECT count(*) FROM sqlite_master "
            "WHERE type='table' AND name='migration_content_adoptions'"
        ).fetchone()[0]
        == 0
    )

    assert tool.main(_argv(wheel, manifest, evidence, digest, mode="prepare")) == 0
    output = capsys.readouterr().out
    assert "additive digest/evidence schema committed" in output
    assert "artifact verification receipt:" in output
    assert SOURCE_REPOSITORY in output
    assert str(tmp_path) not in output
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
    assert len(verification_calls) == 12
    for command in verification_calls:
        assert command[:3] == ("/usr/bin/gh", "attestation", "verify")
        assert ("--repo", SOURCE_REPOSITORY) == command[4:6]
        assert command[6:8] == (
            "--signer-workflow",
            f"{SOURCE_REPOSITORY}/.github/workflows/yoke-build-artifacts.yml",
        )
        assert "--deny-self-hosted-runners" in command
        assert ("--source-digest", SOURCE_COMMIT) == command[8:10]
        assert command[-2:] == ("--format", "json")


def test_admin_surface_rejects_external_evidence_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wheel, manifest, evidence, digest = _artifact(tmp_path)
    _mock_github_attestations(monkeypatch)
    _mock_admin_authority(monkeypatch)
    conn = _legacy_connection()
    conn.execute(
        "INSERT INTO applied_migrations "
        "(migration_name, applied_at, applied_by) "
        "VALUES ('0001_existing', 'now', 'legacy')"
    )
    conn.commit()
    _mock_database_connection(monkeypatch, conn)

    assert tool.main(_argv(wheel, manifest, evidence, digest, mode="prepare")) == 0
    assert tool.main(_argv(wheel, manifest, evidence, "f" * 64, mode="apply")) == 1
    assert (
        conn.execute("SELECT content_sha256 FROM applied_migrations").fetchone()[0]
        is None
    )


def test_admin_surface_refuses_failed_or_mismatched_attestation_before_prepare(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wheel, manifest, evidence, digest = _artifact(tmp_path)
    conn = _legacy_connection()
    _mock_admin_authority(monkeypatch)
    _mock_database_connection(monkeypatch, conn)
    calls = _mock_github_attestations(monkeypatch, returncode=1)

    assert tool.main(_argv(wheel, manifest, evidence, digest, mode="prepare")) == 1
    assert len(calls) == 1
    assert (
        conn.execute(
            "SELECT count(*) FROM sqlite_master "
            "WHERE type='table' AND name='migration_content_adoptions'"
        ).fetchone()[0]
        == 0
    )

    calls = _mock_github_attestations(
        monkeypatch,
        digest_overrides={wheel.name: "f" * 64},
    )
    assert tool.main(_argv(wheel, manifest, evidence, digest, mode="prepare")) == 1
    assert len(calls) == 3
    assert (
        conn.execute(
            "SELECT count(*) FROM sqlite_master "
            "WHERE type='table' AND name='migration_content_adoptions'"
        ).fetchone()[0]
        == 0
    )


def test_admin_surface_refuses_missing_verifier_tool_and_release_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wheel, manifest, evidence, digest = _artifact(tmp_path)
    conn = _legacy_connection()
    _mock_database_connection(monkeypatch, conn)
    monkeypatch.setattr(
        github_artifact_attestation,
        "_resolve_executable",
        lambda _executable: (_ for _ in ()).throw(
            ValueError("GitHub CLI is unavailable")
        ),
    )

    assert tool.main(_argv(wheel, manifest, evidence, digest, mode="prepare")) == 1
    assert (
        conn.execute(
            "SELECT count(*) FROM sqlite_master "
            "WHERE type='table' AND name='migration_content_adoptions'"
        ).fetchone()[0]
        == 0
    )

    evidence.unlink()
    assert tool.main(_argv(wheel, manifest, evidence, digest, mode="prepare")) == 1
