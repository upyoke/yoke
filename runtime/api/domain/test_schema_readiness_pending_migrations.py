"""Coverage for the pending-migration health predicate."""

from __future__ import annotations

import sqlite3

from yoke_core.domain import migrations as migration_history_package
from yoke_core.domain.migration_history import history_dir, ordered_entries
from yoke_core.domain.schema_readiness import pending_migration_names


def _ledger_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE applied_migrations ("
        "migration_name TEXT PRIMARY KEY, applied_at TEXT NOT NULL, "
        "applied_by TEXT)"
    )
    conn.commit()
    return conn


def _packaged_history_names() -> list[str]:
    return [
        entry.name
        for entry in ordered_entries(history_dir(migration_history_package))
    ]


def test_empty_ledger_reports_the_whole_history_pending() -> None:
    conn = _ledger_connection()

    assert pending_migration_names(conn) == _packaged_history_names()


def test_fully_stamped_ledger_reports_nothing_pending() -> None:
    conn = _ledger_connection()
    for name in _packaged_history_names():
        conn.execute(
            "INSERT INTO applied_migrations VALUES (?, 'now', 'test')", (name,)
        )
    conn.commit()

    assert pending_migration_names(conn) == []


def test_missing_ledger_table_reads_as_not_current() -> None:
    # "Cannot tell" and "not current" must be the same answer at this
    # altitude: a health gate that fails open on a broken probe is worse than
    # one that reports not-ready.
    conn = sqlite3.connect(":memory:")

    assert pending_migration_names(conn) == _packaged_history_names()
