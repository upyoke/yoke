"""Boot migration owns fresh and pre-membership application schemas."""

from __future__ import annotations

import os
import sqlite3
import sys

import pytest

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP_DIR)

import db.migrations.migrate as migration_runner  # noqa: E402
from db.migrations.receipt_guards import RECEIPT_COLUMNS  # noqa: E402
from tests.conftest import (  # noqa: E402
    _apply_schema,
    adoption_arguments,
    write_adoption_manifest,
)

EXPECTED_TABLES = {"orgs", "org_members", "sessions", "users"}


def _tables(database) -> set[str]:
    conn = sqlite3.connect(database)
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    conn.close()
    return {str(row[0]) for row in rows}


def test_fresh_boot_creates_application_schema(tmp_path) -> None:
    database = tmp_path / "fresh.db"

    result = migration_runner.migrate(
        db_path=database,
        running_version="1.0.0",
    )

    assert EXPECTED_TABLES <= _tables(database)
    assert result["data"]["applied"] == ["0001_initial_schema"]
    assert result["data"]["ready"] is True
    assert result["data"]["restore_point"]


def test_existing_legacy_database_adopts_from_exact_manifest(
    tmp_path,
) -> None:
    database = tmp_path / "legacy.db"
    conn = sqlite3.connect(database)
    _apply_schema(conn)
    conn.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY)")
    conn.execute("INSERT INTO schema_version VALUES (1)")
    conn.commit()
    conn.close()
    entry = migration_runner.ordered_history()[0]
    manifest, manifest_sha256 = write_adoption_manifest(
        tmp_path / "adopt.json",
        {entry.name: migration_runner.module_sha256(entry)},
    )

    result = migration_runner.migrate(
        db_path=database,
        running_version="1.0.0",
        adoption_manifest=manifest,
        **adoption_arguments(manifest_sha256),
    )

    conn = sqlite3.connect(database)
    row = conn.execute(
        "SELECT migration_name, content_sha256 FROM schema_version WHERE version=1"
    ).fetchone()
    conn.close()
    assert row == ("0001_initial_schema", migration_runner.module_sha256(entry))
    assert EXPECTED_TABLES <= _tables(database)
    assert result["data"]["pending"] == []
    assert result["data"]["ready"] is True


def test_applied_migration_with_missing_declared_floor_blocks_readiness(
    tmp_path,
    monkeypatch,
) -> None:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "0001_retire_surface.py").write_text(
        "MINIMUM_SERVING_VERSION = '2.0.0'\n"
        "def apply(conn):\n"
        "    raise AssertionError('an applied migration must not run again')\n"
    )
    monkeypatch.setattr(migration_runner, "MIGRATIONS_DIR", migrations)
    entry = migration_runner.ordered_history()[0]

    database = tmp_path / "missing-floor.db"
    conn = sqlite3.connect(database)
    conn.execute(
        "CREATE TABLE schema_version ("
        "migration_name TEXT PRIMARY KEY, version INTEGER UNIQUE, "
        "applied_at DATETIME DEFAULT (datetime('now')), "
        "minimum_serving_version TEXT, content_sha256 TEXT)"
    )
    conn.execute(
        "INSERT INTO schema_version "
        "(migration_name, version, minimum_serving_version, content_sha256) "
        "VALUES ('0001_retire_surface', 1, NULL, ?)",
        (migration_runner.module_sha256(entry),),
    )
    migration_runner.ensure_schema_version(
        conn,
        (entry,),
        commit=False,
        repair_adoption_guards=True,
    )
    conn.commit()
    conn.close()

    with pytest.raises(RuntimeError, match="declared serving floor is absent"):
        migration_runner.migrate(
            db_path=database,
            running_version="2.0.0",
        )

    conn = sqlite3.connect(database)
    recorded = conn.execute(
        "SELECT minimum_serving_version FROM schema_version "
        "WHERE migration_name='0001_retire_surface'"
    ).fetchone()
    conn.close()
    assert recorded == (None,)


def test_missing_artifact_verifier_precedes_database_access(tmp_path) -> None:
    entry = migration_runner.ordered_history()[0]
    manifest, manifest_sha256 = write_adoption_manifest(
        tmp_path / "adopt.json",
        {entry.name: migration_runner.module_sha256(entry)},
    )
    arguments = adoption_arguments(manifest_sha256)
    arguments["adoption_artifact_verifier"] = None
    database = tmp_path / "must-not-open.db"

    with pytest.raises(RuntimeError, match="project-owned artifact evidence"):
        migration_runner.migrate(
            db_path=database,
            running_version="1.0.0",
            adoption_manifest=manifest,
            **arguments,
        )

    assert database.exists() is False


def test_older_manifest_subset_adopts_missing_floor_with_newer_runtime(
    tmp_path,
    monkeypatch,
) -> None:
    history_dir = tmp_path / "history"
    history_dir.mkdir()
    (history_dir / "0001_existing.py").write_text(
        "MINIMUM_SERVING_VERSION = '2.0.0'\n"
        "def apply(conn):\n    raise AssertionError('already applied')\n"
        "def invariants(conn):\n"
        "    assert conn.execute('SELECT value FROM marks').fetchone()[0] == 'ok'\n"
    )
    (history_dir / "0002_appended.py").write_text(
        "def apply(conn):\n    raise AssertionError('already applied')\n"
        "def invariants(conn):\n    conn.execute('SELECT 1').fetchone()\n"
    )
    monkeypatch.setattr(migration_runner, "MIGRATIONS_DIR", history_dir)
    history = migration_runner.ordered_history()
    database = tmp_path / "app.db"
    conn = sqlite3.connect(database)
    conn.execute("CREATE TABLE marks (value TEXT)")
    conn.execute("INSERT INTO marks VALUES ('ok')")
    conn.execute(
        "CREATE TABLE schema_version ("
        "migration_name TEXT PRIMARY KEY, version INTEGER UNIQUE, "
        "applied_at DATETIME DEFAULT (datetime('now')), "
        "minimum_serving_version TEXT, content_sha256 TEXT)"
    )
    conn.executemany(
        "INSERT INTO schema_version "
        "(migration_name, version, minimum_serving_version, content_sha256) "
        "VALUES (?, ?, NULL, ?)",
        [
            (entry.name, entry.sequence, migration_runner.module_sha256(entry))
            for entry in history
        ],
    )
    conn.commit()
    conn.close()
    manifest, manifest_sha256 = write_adoption_manifest(
        tmp_path / "older-artifact.json",
        {history[0].name: migration_runner.module_sha256(history[0])},
        engine_version="1.0.0",
    )

    result = migration_runner.migrate(
        db_path=database,
        running_version="3.0.0",
        adoption_manifest=manifest,
        **adoption_arguments(manifest_sha256),
    )

    conn = sqlite3.connect(database)
    floor = conn.execute(
        "SELECT minimum_serving_version FROM schema_version WHERE version=1"
    ).fetchone()
    receipted_floor = conn.execute(
        "SELECT json_extract(adopted_entries_json, "
        "'$[0].minimum_serving_version') FROM migration_adoption_receipts"
    ).fetchone()
    conn.close()
    assert floor == ("2.0.0",)
    assert receipted_floor == ("2.0.0",)
    assert result["data"]["adopted"] == ["0001_existing"]
    assert result["data"]["pending"] == []
    assert result["data"]["ready"] is True


def test_manifest_must_cover_every_legacy_candidate(tmp_path, monkeypatch) -> None:
    history_dir = tmp_path / "history"
    history_dir.mkdir()
    source = (
        "def apply(conn):\n    raise AssertionError('already applied')\n"
        "def invariants(conn):\n    conn.execute('SELECT 1').fetchone()\n"
    )
    (history_dir / "0001_first.py").write_text(source)
    (history_dir / "0002_second.py").write_text(source)
    monkeypatch.setattr(migration_runner, "MIGRATIONS_DIR", history_dir)
    history = migration_runner.ordered_history()
    database = tmp_path / "app.db"
    conn = sqlite3.connect(database)
    conn.execute(
        "CREATE TABLE schema_version ("
        "migration_name TEXT PRIMARY KEY, version INTEGER UNIQUE, "
        "applied_at DATETIME DEFAULT (datetime('now')), "
        "minimum_serving_version TEXT, content_sha256 TEXT)"
    )
    conn.executemany(
        "INSERT INTO schema_version (migration_name, version) VALUES (?, ?)",
        [(entry.name, entry.sequence) for entry in history],
    )
    conn.commit()
    conn.close()
    manifest, digest = write_adoption_manifest(
        tmp_path / "partial.json",
        {history[0].name: migration_runner.module_sha256(history[0])},
    )

    with pytest.raises(RuntimeError, match="does not cover every legacy"):
        migration_runner.migrate(
            db_path=database,
            running_version="1.0.0",
            adoption_manifest=manifest,
            **adoption_arguments(digest),
        )

    conn = sqlite3.connect(database)
    assert conn.execute(
        "SELECT content_sha256 FROM schema_version ORDER BY version"
    ).fetchall() == [(None,), (None,)]
    conn.close()


def test_named_sequence_mismatch_blocks_readiness(tmp_path) -> None:
    database = tmp_path / "sequence-mismatch.db"
    migration_runner.migrate(db_path=database, running_version="1.0.0")
    history = migration_runner.ordered_history()
    entry = history[0]
    conn = sqlite3.connect(database)
    conn.execute("DROP TRIGGER migration_membership_guard_update")
    conn.execute(
        "UPDATE schema_version SET version=2 WHERE migration_name=?", (entry.name,)
    )
    migration_runner.ensure_schema_version(
        conn,
        history,
        commit=False,
        repair_adoption_guards=True,
    )
    conn.commit()

    state = migration_runner.migration_state(conn, running_version="1.0.0")
    conn.close()

    assert state["ready"] is False
    assert state["content_identity_ready"] is False
    assert state["pending"] == [entry.name]
    assert state["sequence_mismatches"] == [
        {"name": entry.name, "recorded_sequence": 2, "expected_sequence": 1}
    ]


@pytest.mark.parametrize(
    ("alteration", "missing", "unexpected"),
    [
        (
            "ALTER TABLE migration_adoption_receipts DROP COLUMN source_commit",
            ["source_commit"],
            [],
        ),
        (
            "ALTER TABLE migration_adoption_receipts ADD COLUMN untracked TEXT",
            [],
            ["untracked"],
        ),
    ],
)
def test_inexact_receipt_shape_blocks_readiness(
    tmp_path,
    alteration,
    missing,
    unexpected,
) -> None:
    database = tmp_path / "receipt-shape.db"
    migration_runner.migrate(db_path=database, running_version="1.0.0")
    conn = sqlite3.connect(database)
    conn.execute(alteration)

    state = migration_runner.migration_state(conn, running_version="1.0.0")
    conn.close()

    assert state["ready"] is False
    assert state["missing_adoption_receipt_guards"] == [
        "migration_adoption_receipts_columns",
        "migration_adoption_receipts_shape",
    ]
    assert state["missing_adoption_receipt_columns"] == missing
    assert state["unexpected_adoption_receipt_columns"] == unexpected


def test_lookalike_receipt_constraints_are_refused(tmp_path) -> None:
    database = tmp_path / "lookalike-receipt.db"
    conn = sqlite3.connect(database)
    columns = ", ".join(f"{name} TEXT" for name in sorted(RECEIPT_COLUMNS))
    conn.execute(f"CREATE TABLE migration_adoption_receipts ({columns})")
    conn.commit()
    conn.close()

    with pytest.raises(RuntimeError, match="incompatible exact shape"):
        migration_runner.migrate(db_path=database, running_version="1.0.0")
