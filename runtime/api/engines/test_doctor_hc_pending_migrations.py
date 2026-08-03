"""Tests for HC-pending-migrations."""

from __future__ import annotations

import sqlite3

from yoke_core.domain import migrations as migration_history_package
from yoke_core.domain.migration_history import history_dir, ordered_entries
from yoke_core.engines.doctor_hc_pending_migrations import hc_pending_migrations
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


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


def _run(conn) -> RecordCollector:
    rec = RecordCollector()
    hc_pending_migrations(conn, DoctorArgs(), rec)
    return rec


def _only_record(rec: RecordCollector):
    assert len(rec.results) == 1, rec.results
    return rec.results[0]


def test_fails_when_the_database_is_behind_its_code() -> None:
    record = _only_record(_run(_ledger_connection()))

    assert record.result == "FAIL"
    # Every outstanding entry is named, so the reader knows what is missing
    # rather than only that something is.
    for name in _packaged_history_names():
        assert name in record.detail


def test_passes_when_the_ledger_is_level() -> None:
    conn = _ledger_connection()
    for name in _packaged_history_names():
        conn.execute(
            "INSERT INTO applied_migrations VALUES (?, 'now', 'test')", (name,)
        )
    conn.commit()

    record = _only_record(_run(conn))

    assert record.result == "PASS"


def test_an_unreadable_ledger_warns_rather_than_passing() -> None:
    # The predecessor passed closed. Under these semantics "I could not read
    # the ledger" and "the ledger is level" are opposite answers, and only
    # one of them is safe to assume.
    conn = sqlite3.connect(":memory:")

    record = _only_record(_run(conn))

    assert record.result == "WARN"
    assert "applied_migrations" in record.detail
