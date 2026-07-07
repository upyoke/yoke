"""Tests for the universe-export engine surface.

The real-artifact tests run pg_dump/pg_restore from ``PATH`` against the
test cluster (an isolated machine home keeps the embedded-binaries
resolver empty); authority-refusal tests drive the machine-config
connection contract through a temp config.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from yoke_contracts.machine_config import runtime as machine_runtime
from yoke_core.domain import universe_export as ux
from yoke_core.domain import yoke_connected_env
from yoke_core.domain.json_helper import dumps_pretty


@pytest.fixture(autouse=True)
def _isolated_machine_home(monkeypatch, tmp_path):
    monkeypatch.setenv(machine_runtime.HOME_ENV, str(tmp_path / "machine-home"))
    monkeypatch.delenv(machine_runtime.CONFIG_FILE_ENV, raising=False)
    monkeypatch.delenv("YOKE_ENV", raising=False)


@contextlib.contextmanager
def _schema_loaded_universe():
    """Yield ``(conn, dsn)`` for a fresh schema-loaded disposable database.

    The fixture schema seeds the default org identity card, so the
    database looks like a bootstrapped universe to the export probe.
    """
    from runtime.api.fixtures import pg_testdb
    from yoke_core.domain import db_backend

    with pg_testdb.test_database() as conn:
        yield conn, os.environ[db_backend.PG_DSN_ENV]


def _write_machine_config(machine_home: Path, payload: dict) -> None:
    machine_home.mkdir(parents=True, exist_ok=True)
    (machine_home / "config.json").write_text(
        dumps_pretty(payload), encoding="utf-8",
    )


def test_default_artifact_name_embeds_slug_and_utc_timestamp():
    moment = datetime(2026, 7, 6, 12, 34, 56, tzinfo=timezone.utc)
    assert ux.default_artifact_name("default", moment) == (
        "default-universe-20260706T123456Z.dump"
    )


def test_default_artifact_name_sanitizes_hostile_slug():
    moment = datetime(2026, 7, 6, 12, 34, 56, tzinfo=timezone.utc)
    name = ux.default_artifact_name("my org/../etc", moment)
    assert name == "my-org-..-etc-universe-20260706T123456Z.dump"
    assert "/" not in name


def test_export_produces_pg_restore_listable_artifact(tmp_path):
    out_dir = tmp_path / "exports"
    out_dir.mkdir()
    emitted: list[str] = []
    with _schema_loaded_universe() as (_conn, dsn):
        report = ux.export_universe(dsn=dsn, out=out_dir, emit=emitted.append)

    artifact = Path(report["artifact"])
    assert artifact.parent == out_dir
    assert artifact.name.startswith("default-universe-")
    assert artifact.name.endswith(ux.ARTIFACT_SUFFIX)
    assert artifact.is_file()
    assert report["bytes"] == artifact.stat().st_size > 0
    assert report["format"] == ux.ARTIFACT_FORMAT
    assert report["org"] == "default"
    assert any("universe-export" in line for line in emitted)

    listing = subprocess.run(
        ["pg_restore", "--list", str(artifact)],
        capture_output=True, text=True,
    )
    assert listing.returncode == 0, listing.stderr
    assert "organizations" in listing.stdout
    assert "actors" in listing.stdout


def test_export_honors_explicit_out_file_path(tmp_path):
    dest = tmp_path / "nested" / "graduation.dump"
    with _schema_loaded_universe() as (_conn, dsn):
        report = ux.export_universe(dsn=dsn, out=dest)

    assert Path(report["artifact"]) == dest
    assert dest.is_file() and dest.stat().st_size > 0


def test_export_trailing_separator_creates_directory(tmp_path):
    """``--out ~/backups/`` with the directory absent means directory mode:
    the directory is created and the artifact lands inside it — never a
    suffixless file named after the directory."""
    with _schema_loaded_universe() as (_conn, dsn):
        report = ux.export_universe(dsn=dsn, out=f"{tmp_path / 'backups'}/")

    backups = tmp_path / "backups"
    assert backups.is_dir()
    artifact = Path(report["artifact"])
    assert artifact.parent == backups
    assert artifact.name.endswith(ux.ARTIFACT_SUFFIX)
    assert artifact.is_file() and artifact.stat().st_size > 0


def test_resolve_destination_routes_directory_vs_file(tmp_path):
    existing = tmp_path / "existing"
    existing.mkdir()

    # Existing directory (no trailing separator) -> directory mode.
    dest = ux._resolve_destination(existing, "default")
    assert dest.parent == existing
    assert dest.name.endswith(ux.ARTIFACT_SUFFIX)

    # Trailing separator on a nonexistent directory -> directory mode,
    # created with parents.
    dest = ux._resolve_destination(f"{tmp_path / 'made' / 'deep'}/", "default")
    assert (tmp_path / "made" / "deep").is_dir()
    assert dest.parent == tmp_path / "made" / "deep"

    # Anything else -> file mode; the parent is created for the dump.
    explicit = tmp_path / "files" / "x.dump"
    assert ux._resolve_destination(explicit, "default") == explicit
    assert explicit.parent.is_dir()
    assert not explicit.exists()


def test_export_refuses_database_without_org_card(tmp_path):
    with _schema_loaded_universe() as (conn, dsn):
        conn.execute("DELETE FROM organizations")
        conn.commit()
        with pytest.raises(ux.UniverseExportError) as excinfo:
            ux.export_universe(dsn=dsn, out=tmp_path)
    assert "no organization identity card" in str(excinfo.value)


def test_export_raises_typed_error_when_pg_dump_missing(monkeypatch, tmp_path):
    with _schema_loaded_universe() as (_conn, dsn):
        # Isolated machine home has no embedded binaries; an empty PATH dir
        # removes the fallback, mirroring the local-universe resolver tests.
        monkeypatch.setenv("PATH", str(tmp_path / "no-binaries-here"))
        with pytest.raises(ux.UniverseExportError) as excinfo:
            ux.export_universe(dsn=dsn, out=tmp_path)
    message = str(excinfo.value)
    assert "pg_dump is missing" in message
    assert "yoke local-postgres start" in message


def test_export_prefers_embedded_pg_dump_and_cleans_failed_artifact(
    tmp_path,
):
    """A fake embedded pg_dump proves installed-binaries-first resolution;
    its failure exit proves the stderr surfacing + truncated-artifact
    cleanup contract."""
    from yoke_core.domain import postgres_binaries

    bin_dir = postgres_binaries.version_dir() / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "initdb").write_text("#!/bin/sh\n", encoding="utf-8")
    fake_pg_dump = bin_dir / "pg_dump"
    fake_pg_dump.write_text(
        "#!/bin/sh\necho 'pg_dump: error: simulated failure' >&2\nexit 1\n",
        encoding="utf-8",
    )
    fake_pg_dump.chmod(0o755)
    dest = tmp_path / "x.dump"
    with _schema_loaded_universe() as (_conn, dsn):
        with pytest.raises(ux.UniverseExportError) as excinfo:
            ux.export_universe(dsn=dsn, out=dest)
    assert "simulated failure" in str(excinfo.value)
    assert not dest.exists()


def _enable_connected_env(monkeypatch) -> None:
    monkeypatch.setenv(yoke_connected_env.PYTEST_ENABLE_ENV, "1")
    monkeypatch.delenv(yoke_connected_env.DISABLE_ENV, raising=False)


def test_resolve_export_dsn_refuses_https_connection_in_mode_language(
    monkeypatch, tmp_path,
):
    _enable_connected_env(monkeypatch)
    _write_machine_config(tmp_path / "machine-home", {
        "schema_version": 1,
        "active_env": "prod",
        "connections": {
            "prod": {
                "transport": "https",
                "api_url": "https://api.example",
                "credential_source": {
                    "kind": "token_file",
                    "path": str(tmp_path / "token"),
                },
            },
        },
    })

    with pytest.raises(ux.UniverseExportError) as excinfo:
        ux.resolve_export_dsn()

    message = str(excinfo.value)
    assert "DSN possession" in message
    assert "hosted" in message
    assert "platform surface" in message
    assert "yoke init --local" in message


def test_resolve_export_dsn_refuses_prod_flagged_postgres(monkeypatch, tmp_path):
    _enable_connected_env(monkeypatch)
    dsn_file = tmp_path / "prod.dsn"
    dsn_file.write_text("host=/prod-sock user=yoke dbname=yoke\n", encoding="utf-8")
    _write_machine_config(tmp_path / "machine-home", {
        "schema_version": 1,
        "active_env": "prod-db-admin",
        "connections": {
            "prod-db-admin": {
                "transport": "local-postgres",
                "prod": True,
                "credential_source": {
                    "kind": "dsn_file",
                    "path": str(dsn_file),
                },
            },
        },
    })

    with pytest.raises(ux.UniverseExportError) as excinfo:
        ux.resolve_export_dsn()

    message = str(excinfo.value)
    assert "prod-flagged" in message
    assert "operator-only" in message


def test_resolve_export_dsn_returns_nonprod_local_postgres_dsn(
    monkeypatch, tmp_path,
):
    _enable_connected_env(monkeypatch)
    dsn_file = tmp_path / "local.dsn"
    dsn_file.write_text("host=/sock user=yoke dbname=yoke\n", encoding="utf-8")
    _write_machine_config(tmp_path / "machine-home", {
        "schema_version": 1,
        "active_env": "local",
        "connections": {
            "local": {
                "transport": "local-postgres",
                "prod": False,
                "credential_source": {
                    "kind": "dsn_file",
                    "path": str(dsn_file),
                },
            },
        },
    })

    assert ux.resolve_export_dsn() == "host=/sock user=yoke dbname=yoke"


def test_resolve_export_dsn_teaches_init_when_unconfigured(monkeypatch, tmp_path):
    _enable_connected_env(monkeypatch)
    # No config.json under the isolated machine home: no binding at all.
    with pytest.raises(ux.UniverseExportError) as excinfo:
        ux.resolve_export_dsn()

    assert "yoke init --local" in str(excinfo.value)
