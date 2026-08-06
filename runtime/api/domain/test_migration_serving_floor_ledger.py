"""Serving-floor stamping and permanent-history repair coverage."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from yoke_core.domain.migration_boot_apply import stamp_history
from yoke_core.domain.migration_history import ordered_entries
from yoke_core.domain.migration_serving_floor_ledger import (
    backfill_serving_floors,
    missing_declared_serving_floors,
)
from yoke_core.domain.migration_yoke_ledger import (
    YOKE_LEDGER_CONTRACT,
    ensure_yoke_migration_ledger,
)


def _connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    ensure_yoke_migration_ledger(conn)
    conn.execute("CREATE TABLE marks (name TEXT)")
    return conn


def _history(tmp_path: Path):
    (tmp_path / "0001_retire_surface.py").write_text(
        "MINIMUM_SERVING_VERSION = '2.4.0'\n"
        "def apply(conn):\n"
        "    conn.execute(\"INSERT INTO marks VALUES ('must-not-run')\")\n"
    )
    return ordered_entries(tmp_path)


def test_birth_stamp_records_each_entry_serving_floor(tmp_path: Path) -> None:
    conn = _connection()
    stamp_history(
        conn,
        _history(tmp_path),
        ledger=YOKE_LEDGER_CONTRACT,
        applied_by="birth",
    )

    row = conn.execute(
        "SELECT minimum_serving_version FROM applied_migrations "
        "WHERE migration_name='0001_retire_surface'"
    ).fetchone()
    assert row == ("2.4.0",)
    assert conn.execute("SELECT * FROM marks").fetchall() == []


def test_missing_floor_is_reconstructed_from_permanent_history(
    tmp_path: Path,
) -> None:
    conn = _connection()
    history = _history(tmp_path)
    conn.execute(
        "INSERT INTO applied_migrations "
        "(migration_name, applied_at, applied_by, minimum_serving_version) "
        "VALUES ('0001_retire_surface', 'now', 'old-stamp', NULL)"
    )

    assert missing_declared_serving_floors(
        conn, history, ledger=YOKE_LEDGER_CONTRACT,
    ) == (
        "0001_retire_surface",
    )
    assert backfill_serving_floors(
        conn, history, ledger=YOKE_LEDGER_CONTRACT,
    ) == ("0001_retire_surface",)
    assert missing_declared_serving_floors(
        conn, history, ledger=YOKE_LEDGER_CONTRACT,
    ) == ()
