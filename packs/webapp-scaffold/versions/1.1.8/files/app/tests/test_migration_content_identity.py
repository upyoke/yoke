"""Migration membership is bound to exact module bytes."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import sys

import pytest


APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP_DIR)

from db.migrations import migrate as migration_runner  # noqa: E402


def _entry(directory, name: str, source: str):
    path = directory / f"{name}.py"
    path.write_text(source, encoding="utf-8")
    return path


def _digest(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ledger(conn) -> None:
    conn.execute(
        "CREATE TABLE schema_version ("
        "migration_name TEXT PRIMARY KEY, version INTEGER UNIQUE, "
        "applied_at DATETIME DEFAULT (datetime('now')), "
        "minimum_serving_version TEXT, content_sha256 TEXT)"
    )


def test_fresh_apply_records_exact_bytes_and_current_boot_is_idempotent(
    tmp_path,
    monkeypatch,
) -> None:
    history = tmp_path / "history"
    history.mkdir()
    module = _entry(
        history,
        "0001_create_marks",
        "def apply(conn):\n"
        "    conn.execute('CREATE TABLE marks (value TEXT)')\n"
        "def invariants(conn):\n"
        "    conn.execute('SELECT value FROM marks').fetchall()\n",
    )
    monkeypatch.setattr(migration_runner, "MIGRATIONS_DIR", history)
    database = tmp_path / "app.db"

    first = migration_runner.migrate(
        db_path=database,
        running_version="1.0.0",
    )
    second = migration_runner.migrate(
        db_path=database,
        running_version="1.0.0",
    )
    conn = sqlite3.connect(database)
    row = conn.execute(
        "SELECT migration_name, content_sha256 FROM schema_version"
    ).fetchone()
    receipt_table = conn.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name='migration_adoption_receipts'"
    ).fetchone()
    conn.close()
    assert row == ("0001_create_marks", _digest(module))
    assert receipt_table == ("migration_adoption_receipts",)
    assert first["data"]["applied"] == ["0001_create_marks"]
    assert first["data"]["content_identity_ready"] is True
    assert first["data"]["adoption_receipt_guards_ready"] is True
    assert second["data"]["applied"] == []
    assert second["data"]["restore_point"] is None


def test_non_null_drift_fails_before_backup_or_current_return(
    tmp_path,
    monkeypatch,
) -> None:
    history = tmp_path / "history"
    history.mkdir()
    module = _entry(
        history,
        "0001_create_marks",
        "def apply(conn):\n"
        "    conn.execute('CREATE TABLE marks (value TEXT)')\n"
        "def invariants(conn):\n"
        "    conn.execute('SELECT value FROM marks').fetchall()\n",
    )
    monkeypatch.setattr(migration_runner, "MIGRATIONS_DIR", history)
    database = tmp_path / "app.db"
    migration_runner.migrate(db_path=database, running_version="1.0.0")
    backup_dir = tmp_path / "migration-backups"
    before_backups = sorted(backup_dir.iterdir())
    conn = sqlite3.connect(database)
    before_row = conn.execute("SELECT * FROM schema_version").fetchone()
    conn.close()
    module.write_bytes(module.read_bytes() + b"# changed after apply\n")

    with pytest.raises(RuntimeError, match="content identity mismatch"):
        migration_runner.migrate(db_path=database, running_version="1.0.0")

    conn = sqlite3.connect(database)
    after_row = conn.execute("SELECT * FROM schema_version").fetchone()
    conn.close()
    assert after_row == before_row
    assert sorted(backup_dir.iterdir()) == before_backups


def test_name_only_legacy_row_reports_adoption_without_autofill(
    tmp_path,
    monkeypatch,
) -> None:
    history = tmp_path / "history"
    history.mkdir()
    _entry(
        history,
        "0001_existing",
        "def apply(conn):\n"
        "    raise AssertionError('must not replay legacy membership')\n"
        "def invariants(conn):\n"
        "    assert conn.execute('SELECT value FROM marks').fetchone()[0] == 'ok'\n",
    )
    monkeypatch.setattr(migration_runner, "MIGRATIONS_DIR", history)
    database = tmp_path / "app.db"
    conn = sqlite3.connect(database)
    conn.execute("CREATE TABLE marks (value TEXT)")
    conn.execute("INSERT INTO marks VALUES ('ok')")
    _ledger(conn)
    conn.execute(
        "INSERT INTO schema_version (migration_name, version) "
        "VALUES ('0001_existing', 1)"
    )
    migration_runner.ensure_schema_version(
        conn,
        migration_runner.ordered_history(),
        commit=False,
        repair_adoption_guards=True,
    )
    conn.commit()
    state = migration_runner.migration_state(conn, running_version="1.0.0")
    conn.close()

    assert state["adoption_required"] == ["0001_existing"]
    assert state["content_identity_ready"] is False
    assert state["pending"] == []
    with pytest.raises(RuntimeError, match="requires explicit artifact-verified"):
        migration_runner.migrate(db_path=database, running_version="1.0.0")
    conn = sqlite3.connect(database)
    assert conn.execute("SELECT content_sha256 FROM schema_version").fetchone() == (
        None,
    )
    conn.close()


def test_ledger_ahead_remains_serving_safe_for_an_older_artifact(
    tmp_path,
    monkeypatch,
) -> None:
    history = tmp_path / "history"
    history.mkdir()
    module = _entry(
        history,
        "0001_existing",
        "def apply(conn):\n    raise AssertionError('already applied')\n"
        "def invariants(conn):\n    pass\n",
    )
    monkeypatch.setattr(migration_runner, "MIGRATIONS_DIR", history)
    database = tmp_path / "app.db"
    conn = sqlite3.connect(database)
    _ledger(conn)
    conn.execute(
        "INSERT INTO schema_version VALUES (?, ?, NULL, NULL, ?)",
        ("0001_existing", 1, _digest(module)),
    )
    conn.execute(
        "INSERT INTO schema_version VALUES (?, ?, NULL, ?, ?)",
        ("0002_future", 2, "0.9.0", "f" * 64),
    )
    migration_runner.ensure_schema_version(
        conn,
        migration_runner.ordered_history(),
        commit=False,
        repair_adoption_guards=True,
    )
    conn.commit()
    conn.close()

    result = migration_runner.migrate(
        db_path=database,
        running_version="1.0.0",
    )

    assert result["data"]["ready"] is True
    assert result["data"]["ledger_ahead"] == ["0002_future"]
    assert result["data"]["restore_point"] is None


@pytest.mark.parametrize(
    ("recorded_floor", "running_version", "message"),
    [
        (None, "1.0.0", "has no serving floor"),
        ("   ", "1.0.0", "has no serving floor"),
        ("2.0.0", "1.0.0", "requires build 2.0.0"),
    ],
)
def test_ledger_ahead_requires_an_identified_compatible_floor(
    tmp_path,
    monkeypatch,
    recorded_floor,
    running_version,
    message,
) -> None:
    history = tmp_path / "history"
    history.mkdir()
    module = _entry(history, "0001_existing", "def apply(conn):\n    pass\n")
    monkeypatch.setattr(migration_runner, "MIGRATIONS_DIR", history)
    conn = sqlite3.connect(tmp_path / "app.db")
    _ledger(conn)
    conn.execute(
        "INSERT INTO schema_version VALUES (?, ?, NULL, NULL, ?)",
        ("0001_existing", 1, _digest(module)),
    )
    conn.execute(
        "INSERT INTO schema_version VALUES (?, ?, NULL, ?, ?)",
        ("0002_future", 2, recorded_floor, "f" * 64),
    )
    conn.commit()

    state = migration_runner.migration_state(
        conn,
        running_version=running_version,
    )
    conn.close()

    assert state["ready"] is False
    assert any(message in reason for reason in state["stranded"])


@pytest.mark.parametrize(
    ("recorded_floor", "reason"),
    [
        (None, "0001_existing: declared serving floor is absent"),
        ("1.5.0", "0001_existing: recorded floor '1.5.0' != packaged '2.0.0'"),
    ],
)
def test_known_recorded_floor_must_match_packaged_declaration(
    tmp_path,
    monkeypatch,
    recorded_floor,
    reason,
) -> None:
    history = tmp_path / "history"
    history.mkdir()
    module = _entry(
        history,
        "0001_existing",
        "MINIMUM_SERVING_VERSION = '2.0.0'\ndef apply(conn):\n    pass\n",
    )
    monkeypatch.setattr(migration_runner, "MIGRATIONS_DIR", history)
    conn = sqlite3.connect(tmp_path / "app.db")
    _ledger(conn)
    conn.execute(
        "INSERT INTO schema_version VALUES (?, ?, NULL, ?, ?)",
        ("0001_existing", 1, recorded_floor, _digest(module)),
    )
    conn.commit()

    state = migration_runner.migration_state(conn, running_version="3.0.0")
    conn.close()

    assert state["ready"] is False
    assert state["stranded"] == [reason]


@pytest.mark.parametrize(
    ("statement", "parameters"),
    [
        ("UPDATE schema_version SET migration_name=?", ("0001_renamed",)),
        ("UPDATE schema_version SET version=?", (2,)),
        ("UPDATE schema_version SET minimum_serving_version=?", ("9.0.0",)),
        ("UPDATE schema_version SET content_sha256=?", ("f" * 64,)),
        ("DELETE FROM schema_version", ()),
    ],
)
def test_applied_membership_is_immutable(statement, parameters, tmp_path) -> None:
    database = tmp_path / "app.db"
    migration_runner.migrate(db_path=database, running_version="1.0.0")
    conn = sqlite3.connect(database)
    before = conn.execute("SELECT * FROM schema_version").fetchall()

    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute(statement, parameters)

    conn.rollback()
    assert conn.execute("SELECT * FROM schema_version").fetchall() == before
    conn.close()


def test_import_time_source_change_never_executes_captured_entry(
    tmp_path,
    monkeypatch,
) -> None:
    history = tmp_path / "history"
    history.mkdir()
    (history / "0001_rewrites_source.py").write_text(
        "from pathlib import Path\n"
        "Path(__file__).write_text('def apply(conn):\\n    pass\\n')\n"
        "def apply(conn):\n"
        "    conn.execute('CREATE TABLE should_not_exist (value TEXT)')\n"
    )
    monkeypatch.setattr(migration_runner, "MIGRATIONS_DIR", history)
    database = tmp_path / "app.db"

    with pytest.raises(RuntimeError, match="source changed while the module loaded"):
        migration_runner.migrate(db_path=database, running_version="1.0.0")

    conn = sqlite3.connect(database)
    assert (
        conn.execute(
            "SELECT name FROM sqlite_master WHERE name='should_not_exist'"
        ).fetchone()
        is None
    )
    assert conn.execute("SELECT COUNT(*) FROM schema_version").fetchone() == (0,)
    conn.close()
