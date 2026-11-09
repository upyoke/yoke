"""HC-migration-content-identity compares the checkout with its ledger."""

from __future__ import annotations

import sqlite3

from yoke_core.domain import migrations as migration_history_package
from yoke_core.domain.migration_history import history_dir, ordered_entries
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector
from yoke_project_checks.check_migration_content_identity import (
    HC_ID,
    hc_migration_content_identity,
)


def _connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE applied_migrations ("
        "migration_name TEXT PRIMARY KEY, content_sha256 TEXT)"
    )
    return conn


def _run(conn: sqlite3.Connection) -> RecordCollector:
    recorder = RecordCollector()
    hc_migration_content_identity(conn, DoctorArgs(), recorder)
    return recorder


def _first_entry():
    return ordered_entries(history_dir(migration_history_package))[0]


def test_passes_when_packaged_and_ledger_digests_match() -> None:
    conn = _connection()
    entry = _first_entry()
    conn.execute(
        "INSERT INTO applied_migrations VALUES (?, ?)",
        (entry.name, entry.content_sha256),
    )

    result = _run(conn).results[0]

    assert result.check_id == HC_ID
    assert result.result == "PASS"
    assert "1 applied migration digest" in result.detail


def test_fails_with_both_identities_when_bytes_differ() -> None:
    conn = _connection()
    entry = _first_entry()
    recorded = "0" * 64
    conn.execute(
        "INSERT INTO applied_migrations VALUES (?, ?)",
        (entry.name, recorded),
    )

    result = _run(conn).results[0]

    assert result.result == "FAIL"
    assert entry.name in result.detail
    assert f"ledger={recorded}" in result.detail
    assert f"packaged={entry.content_sha256}" in result.detail


def test_unreachable_ledger_is_not_a_pass() -> None:
    result = _run(sqlite3.connect(":memory:")).results[0]

    assert result.result == "N/A"
    assert "not reachable" in result.detail


def test_checks_code_baseline_identity_without_scripts(tmp_path, monkeypatch) -> None:
    directory = tmp_path / "migrations"
    directory.mkdir()
    name = "0106_baseline"
    digest = "a" * 64
    (directory / "__init__.py").write_text("HISTORY_BASELINE = " + repr({
        "name": name, "content_sha256": digest,
        "minimum_serving_version": "next-release",
    }))
    monkeypatch.setattr(
        "yoke_project_checks.check_migration_content_identity.history_dir",
        lambda package: directory,
    )
    conn = _connection()
    conn.execute("INSERT INTO applied_migrations VALUES (?, ?)", (name, digest))

    result = _run(conn).results[0]

    assert result.result == "PASS", result.detail
    conn.execute("UPDATE applied_migrations SET content_sha256 = ?", ("b" * 64,))
    result = _run(conn).results[0]
    assert result.result == "FAIL"
    assert name in result.detail
