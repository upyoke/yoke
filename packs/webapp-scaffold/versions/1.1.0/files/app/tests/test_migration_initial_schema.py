"""Boot migration owns fresh and pre-membership application schemas."""

from __future__ import annotations

import os
import sqlite3
import sys

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP_DIR)

from db.migrations.migrate import migrate  # noqa: E402
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

    result = migrate(db_path=database, running_version="1.0.0")

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

    result = migrate(db_path=database, running_version="1.0.0")

    conn = sqlite3.connect(database)
    row = conn.execute(
        "SELECT migration_name FROM schema_version WHERE version=1"
    ).fetchone()
    conn.close()
    assert row == ("0001_initial_schema",)
    assert EXPECTED_TABLES <= _tables(database)
    assert result["data"]["pending"] == []
    assert result["data"]["ready"] is True
