"""Tests for the {{project_display_name}} API health endpoint."""

import os
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace

import pytest

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP_DIR)

httpx = pytest.importorskip("httpx")
pytest.importorskip("fastapi")

from httpx import AsyncClient, ASGITransport  # noqa: E402
from api.main import create_app  # noqa: E402
from db.migrations.migrate import migrate  # noqa: E402
from db.migrations import migrate as migration_runner  # noqa: E402
from tests.conftest import _apply_schema  # noqa: E402
from utils import db as db_utils  # noqa: E402


async def _health_response(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.get("/api/health")


@pytest.fixture
def api_db(tmp_path, monkeypatch):
    """Create a temp DB and point APP_DB_PATH at it."""
    path = str(tmp_path / "api_test.db")
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode = WAL")
    _apply_schema(conn)
    conn.close()
    monkeypatch.setenv("APP_DB_PATH", path)
    migrate(db_path=path, running_version="0.1.0")
    return path


@pytest.fixture
def bad_db_path(tmp_path, monkeypatch):
    """Point APP_DB_PATH at a non-existent path."""
    path = str(tmp_path / "nonexistent" / "missing.db")
    monkeypatch.setenv("APP_DB_PATH", path)
    return path


@pytest.mark.asyncio
async def test_health_ok(api_db):
    """Health endpoint returns ok with valid DB."""
    resp = await _health_response(create_app(db_path=api_db))
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["data"]["db_ok"] is True
    assert data["data"]["version"] == "0.1.0"
    assert "schema_version" in data["data"]
    assert data["data"]["migrations_current"] is True
    assert data["data"]["migration_ready"] is True
    assert data["data"]["migration_content_matches"] is True
    assert data["data"]["migration_content_adoption_required"] == []
    assert data["data"]["migration_adoption_receipt_guards_ready"] is True
    assert data["data"]["missing_migration_adoption_receipt_guards"] == []


@pytest.mark.asyncio
async def test_health_db_missing(bad_db_path):
    """Health endpoint reports db_ok=false when DB is unreachable."""
    resp = await _health_response(create_app(db_path=bad_db_path))
    assert resp.status_code == 503
    data = resp.json()
    assert data["status"] == "error"
    assert data["data"]["db_ok"] is False


@pytest.mark.asyncio
async def test_health_no_auth_required(api_db):
    """Health endpoint does not require authentication."""
    resp = await _health_response(create_app(db_path=api_db))

    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_health_reports_content_identity_adoption_required(
    tmp_path, monkeypatch,
):
    database = tmp_path / "legacy.db"
    conn = sqlite3.connect(database)
    _apply_schema(conn)
    history = migration_runner.ordered_history()
    conn.execute(
        "CREATE TABLE schema_version ("
        "migration_name TEXT PRIMARY KEY, version INTEGER UNIQUE, "
        "applied_at DATETIME DEFAULT (datetime('now')), "
        "minimum_serving_version TEXT, content_sha256 TEXT)"
    )
    conn.execute(
        "INSERT INTO schema_version (migration_name, version) VALUES (?, ?)",
        (history[0].name, history[0].sequence),
    )
    conn.commit()
    conn.close()
    monkeypatch.setenv("APP_DB_PATH", str(database))
    resp = await _health_response(create_app(db_path=str(database)))

    assert resp.status_code == 503
    data = resp.json()["data"]
    assert data["migration_ready"] is False
    assert data["migration_content_matches"] is True
    assert data["migration_content_adoption_required"] == [history[0].name]
    assert data["migration_content_mismatches"] == []


def _entry(directory, name, body="pass", floor=None):
    declaration = (
        f"MINIMUM_SERVING_VERSION = {floor!r}\n" if floor is not None else ""
    )
    (directory / f"{name}.py").write_text(
        declaration + "def apply(conn):\n" + f"    {body}\n"
    )


def _migration_connection(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def test_gap_below_highest_legacy_version_stays_pending(tmp_path, monkeypatch):
    history_dir = tmp_path / "history"
    history_dir.mkdir()
    _entry(history_dir, "0001_first")
    _entry(history_dir, "0002_second")
    monkeypatch.setattr(migration_runner, "MIGRATIONS_DIR", history_dir)
    conn = _migration_connection(tmp_path / "app.db")
    conn.execute(
        "CREATE TABLE schema_version ("
        "version INTEGER PRIMARY KEY, applied_at DATETIME)"
    )
    conn.execute("INSERT INTO schema_version VALUES (2, datetime('now'))")
    conn.commit()
    history = migration_runner.ordered_history()

    migration_runner.ensure_schema_version(conn, history)
    pending = migration_runner.find_pending_migrations(
        history, migration_runner.applied_names(conn, history)
    )

    assert [entry.name for entry in pending] == ["0001_first"]
    assert conn.execute(
        "SELECT migration_name FROM schema_version WHERE version=2"
    ).fetchone()[0] is None


def test_failed_invariants_roll_back_mutation_and_membership(
    tmp_path, monkeypatch,
):
    history_dir = tmp_path / "history"
    history_dir.mkdir()
    (history_dir / "0001_failing.py").write_text(
        "def apply(conn):\n"
        "    conn.execute(\"INSERT INTO marks VALUES ('changed')\")\n"
        "def invariants(conn):\n"
        "    raise AssertionError('not verified')\n"
    )
    monkeypatch.setattr(migration_runner, "MIGRATIONS_DIR", history_dir)
    conn = _migration_connection(tmp_path / "app.db")
    conn.execute("CREATE TABLE marks (name TEXT)")
    history = migration_runner.ordered_history()
    migration_runner.ensure_schema_version(conn, history)

    with pytest.raises(AssertionError, match="not verified"):
        migration_runner.apply_migration(
            conn, history[0], running_version="1.0.0"
        )

    assert conn.execute("SELECT * FROM marks").fetchall() == []
    assert migration_runner.applied_names(conn) == set()


def test_recorded_floor_blocks_an_older_build(tmp_path, monkeypatch):
    history_dir = tmp_path / "history"
    history_dir.mkdir()
    _entry(history_dir, "0001_retire", floor="2.0.0")
    monkeypatch.setattr(migration_runner, "MIGRATIONS_DIR", history_dir)
    conn = _migration_connection(tmp_path / "app.db")
    history = migration_runner.ordered_history()
    migration_runner.ensure_schema_version(conn, history)
    migration_runner.apply_migration(
        conn, history[0], running_version="2.0.0"
    )

    state = migration_runner.migration_state(conn, running_version="1.9.0")

    assert state["ready"] is False
    assert state["pending"] == []
    assert state["stranded"]


def test_unmapped_legacy_row_prevents_readiness(tmp_path, monkeypatch):
    history_dir = tmp_path / "history"
    history_dir.mkdir()
    _entry(history_dir, "0001_first")
    monkeypatch.setattr(migration_runner, "MIGRATIONS_DIR", history_dir)
    conn = _migration_connection(tmp_path / "app.db")
    conn.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY)")
    conn.execute("INSERT INTO schema_version VALUES (99)")
    conn.commit()
    migration_runner.ensure_schema_version(conn, migration_runner.ordered_history())

    state = migration_runner.migration_state(conn, running_version="1.0.0")

    assert state["ready"] is False
    assert state["unmapped_legacy_versions"] == [99]


def test_blank_artifact_version_is_refused_before_database_work(tmp_path):
    database = tmp_path / "must-not-be-created.db"

    with pytest.raises(RuntimeError, match="non-empty running artifact version"):
        migrate(db_path=database, running_version="")

    assert not database.exists()


def test_manual_cli_requires_artifact_version():
    with pytest.raises(SystemExit):
        migration_runner.main([])


def test_pending_apply_creates_a_verified_restore_point_and_noop_does_not(
    tmp_path, monkeypatch,
):
    history_dir = tmp_path / "history"
    history_dir.mkdir()
    _entry(history_dir, "0001_existing")
    _entry(
        history_dir, "0002_change",
        body="conn.execute(\"INSERT INTO marks VALUES ('after')\")",
    )
    monkeypatch.setattr(migration_runner, "MIGRATIONS_DIR", history_dir)
    database = tmp_path / "app.db"
    conn = sqlite3.connect(database)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("CREATE TABLE marks (name TEXT)")
    conn.execute("INSERT INTO marks VALUES ('before')")
    history = migration_runner.ordered_history()
    conn.execute(
        "CREATE TABLE schema_version ("
        "migration_name TEXT PRIMARY KEY, version INTEGER UNIQUE, "
        "applied_at DATETIME DEFAULT (datetime('now')), "
        "minimum_serving_version TEXT, content_sha256 TEXT)"
    )
    conn.execute(
        "INSERT INTO schema_version "
        "(migration_name, version, content_sha256) VALUES (?, ?, ?)",
        (
            history[0].name,
            history[0].sequence,
            migration_runner.module_sha256(history[0]),
        ),
    )
    conn.commit()
    conn.close()
    real_connect = db_utils.sqlite3.connect
    partial_modes = []

    def connect(target, *args, **kwargs):
        candidate = Path(target)
        if candidate.suffix == ".partial":
            partial_modes.append(candidate.stat().st_mode & 0o777)
        return real_connect(target, *args, **kwargs)

    monkeypatch.setattr(db_utils.sqlite3, "connect", connect)

    first = migrate(db_path=database, running_version="1.0.0")
    restore = Path(first["data"]["restore_point"])

    assert restore.is_file()
    assert restore.stat().st_mode & 0o777 == 0o600
    assert restore.parent.stat().st_mode & 0o777 == 0o700
    assert partial_modes == [0o600]
    backup = sqlite3.connect(restore)
    assert backup.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert backup.execute("SELECT name FROM marks").fetchall() == [("before",)]
    columns = {
        row[1] for row in backup.execute("PRAGMA table_info(schema_version)")
    }
    assert columns == {
        "applied_at", "content_sha256", "migration_name",
        "minimum_serving_version", "version",
    }
    backup.close()

    count = len(list(restore.parent.glob("*.db")))
    second = migrate(db_path=database, running_version="1.0.0")
    assert second["data"]["restore_point"] is None
    assert len(list(restore.parent.glob("*.db"))) == count


def test_failed_pending_apply_names_its_restore_point(tmp_path, monkeypatch):
    history_dir = tmp_path / "history"
    history_dir.mkdir()
    _entry(history_dir, "0001_bad", body="raise RuntimeError('broken')")
    monkeypatch.setattr(migration_runner, "MIGRATIONS_DIR", history_dir)
    database = tmp_path / "app.db"
    sqlite3.connect(database).close()

    with pytest.raises(RuntimeError, match="restore point: .*migration-backups"):
        migrate(db_path=database, running_version="1.0.0")


def test_restore_point_failure_removes_the_private_partial(tmp_path):
    database = tmp_path / "app.db"
    conn = sqlite3.connect(database)

    class FailingBackup:
        def execute(self, statement):
            return conn.execute(statement)

        def backup(self, _target):
            raise RuntimeError("backup interrupted")

    with pytest.raises(RuntimeError, match="backup interrupted"):
        db_utils.establish_migration_restore_point(
            FailingBackup(), (SimpleNamespace(name="0001_change"),),
        )

    backup_dir = tmp_path / "migration-backups"
    assert list(backup_dir.iterdir()) == []
    conn.close()


def test_blank_external_restore_point_is_refused_before_database_work(tmp_path):
    database = tmp_path / "must-not-be-created.db"

    with pytest.raises(RuntimeError, match="non-empty identifier"):
        migrate(
            db_path=database,
            running_version="1.0.0",
            external_restore_point="   ",
        )

    assert not database.exists()
