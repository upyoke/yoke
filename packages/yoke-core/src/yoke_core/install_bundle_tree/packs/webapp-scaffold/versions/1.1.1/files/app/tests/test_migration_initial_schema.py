"""Boot migration owns fresh and pre-membership application schemas."""

from __future__ import annotations

import os
import sqlite3
import sys

import pytest

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP_DIR)

import db.migrations.migrate as migration_runner  # noqa: E402
from tests.conftest import _apply_schema  # noqa: E402

EXPECTED_TABLES = {"orgs", "org_members", "sessions", "users"}


def _tables(database) -> set[str]:
    conn = sqlite3.connect(database)
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    conn.close()
    return {str(row[0]) for row in rows}


def test_fresh_boot_creates_application_schema(tmp_path) -> None:
    database = tmp_path / "fresh.db"

    result = migration_runner.migrate(
        db_path=database, running_version="1.0.0",
    )

    assert EXPECTED_TABLES <= _tables(database)
    assert result["data"]["applied"] == ["0001_initial_schema"]
    assert result["data"]["ready"] is True
    assert result["data"]["restore_point"]


def test_existing_legacy_database_adopts_and_verifies_initial_schema(
    tmp_path,
) -> None:
    database = tmp_path / "legacy.db"
    conn = sqlite3.connect(database)
    _apply_schema(conn)
    conn.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY)")
    conn.execute("INSERT INTO schema_version VALUES (1)")
    conn.commit()
    conn.close()

    result = migration_runner.migrate(
        db_path=database, running_version="1.0.0",
    )

    conn = sqlite3.connect(database)
    row = conn.execute(
        "SELECT migration_name FROM schema_version WHERE version=1"
    ).fetchone()
    conn.close()
    assert row == ("0001_initial_schema",)
    assert EXPECTED_TABLES <= _tables(database)
    assert result["data"]["pending"] == []
    assert result["data"]["ready"] is True


def test_applied_migration_with_missing_declared_floor_blocks_readiness(
    tmp_path, monkeypatch,
) -> None:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "0001_retire_surface.py").write_text(
        "MINIMUM_SERVING_VERSION = '2.0.0'\n"
        "def apply(conn):\n"
        "    raise AssertionError('an applied migration must not run again')\n"
    )
    monkeypatch.setattr(migration_runner, "MIGRATIONS_DIR", migrations)

    database = tmp_path / "missing-floor.db"
    conn = sqlite3.connect(database)
    conn.execute(
        "CREATE TABLE schema_version ("
        "migration_name TEXT PRIMARY KEY, version INTEGER UNIQUE, "
        "applied_at DATETIME DEFAULT (datetime('now')), "
        "minimum_serving_version TEXT)"
    )
    conn.execute(
        "INSERT INTO schema_version "
        "(migration_name, version, minimum_serving_version) "
        "VALUES ('0001_retire_surface', 1, NULL)"
    )
    conn.commit()
    conn.close()

    with pytest.raises(RuntimeError, match="declared serving floor is absent"):
        migration_runner.migrate(
            db_path=database, running_version="2.0.0",
        )

    conn = sqlite3.connect(database)
    recorded = conn.execute(
        "SELECT minimum_serving_version FROM schema_version "
        "WHERE migration_name='0001_retire_surface'"
    ).fetchone()
    conn.close()
    assert recorded == (None,)
