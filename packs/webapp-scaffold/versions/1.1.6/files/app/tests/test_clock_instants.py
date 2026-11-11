"""Actual session, task and governed SQLite clock owners."""

from __future__ import annotations

import importlib
from pathlib import Path
import sqlite3
from datetime import datetime

import pytest

from api import auth
from api.tasks import runner
from db.migrations import migrate as migrations
from db.migrations import receipt_guards
from utils.timestamps import InvalidInstant, format_instant, parse_instant

INSTANT = parse_instant("2026-10-09T15:00:00.123456Z")
OPAQUE = "2026-10-09T15:00:00.123456+05:00: arbitrary prose"
conversion = importlib.import_module("db.migrations.0002_canonical_instants")


def _legacy_database(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        (Path(__file__).parent / "fixtures/auth_legacy_schema.sql").read_text()
    )
    conn.execute("INSERT INTO orgs VALUES (1, ?, 'sample', NULL)", (OPAQUE,))
    conn.execute(
        "INSERT INTO users VALUES (1, 'sample@example.test', 'hash', ?, 'admin', 'key', ?)",
        (OPAQUE, "2026-10-09 15:00:00.123455"),
    )
    conn.execute(
        "INSERT INTO org_members VALUES (1, 1, 'owner', ?)",
        ("2026-10-09T20:00:00.123456+05:00",),
    )
    conn.execute(
        "INSERT INTO sessions VALUES ('token', 1, ?, ?)",
        ("2026-10-09T15:00:00.123457", "2026-10-09 15:00:00"),
    )
    history = migrations.ordered_history()
    receipt_guards.ensure_schema_version(conn, history)
    conn.execute(
        "INSERT INTO schema_version (migration_name, version, content_sha256, applied_at) "
        "VALUES (?, ?, ?, ?)",
        (
            history[0].name,
            history[0].sequence,
            migrations.module_sha256(history[0]),
            OPAQUE,
        ),
    )
    conn.execute(
        "INSERT INTO migration_adoption_receipts "
        "(manifest_sha256, engine_version, source_artifact, source_sha256, source_commit, "
        "adopted_by, artifact_verifier, artifact_verification_sha256, adopted_entries_json, recorded_at) "
        "VALUES (?, '0.1.0', 'old', ?, ?, 'operator', 'verified', ?, '[]', ?)",
        ("a" * 64, "b" * 64, "c" * 40, "d" * 64, OPAQUE),
    )
    conn.commit()
    return conn


def test_upgrade_restore_point_precision_guards_and_noop(tmp_path):
    path = tmp_path / "legacy.db"
    conn = _legacy_database(path)
    old_receipt = tuple(
        conn.execute("SELECT * FROM migration_adoption_receipts").fetchone()
    )
    old_ledger = tuple(conn.execute("SELECT * FROM schema_version").fetchone())
    conn.close()
    first = migrations.migrate(db_path=path, running_version="0.2.0")
    backup = sqlite3.connect(first["data"]["restore_point"])
    assert (
        backup.execute("SELECT expires_at FROM sessions").fetchone()[0]
        == "2026-10-09T15:00:00.123457"
    )
    assert backup.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    backup.close()
    conn = sqlite3.connect(path)
    assert conn.execute("SELECT expires_at, created_at FROM sessions").fetchone() == (
        "2026-10-09T15:00:00.123457Z",
        "2026-10-09T15:00:00.000000Z",
    )
    assert conn.execute("SELECT name, created_at FROM orgs").fetchone() == (
        OPAQUE,
        None,
    )
    assert conn.execute("SELECT name, created_at FROM users").fetchone() == (
        OPAQUE,
        "2026-10-09T15:00:00.123455Z",
    )
    assert conn.execute("SELECT created_at FROM org_members").fetchone()[
        0
    ] == format_instant(INSTANT)
    assert (
        tuple(conn.execute("SELECT * FROM migration_adoption_receipts").fetchone())
        == old_receipt
    )
    assert (
        tuple(conn.execute("SELECT * FROM schema_version WHERE version=1").fetchone())
        == old_ledger
    )
    floor, clock = conn.execute(
        "SELECT minimum_serving_version, applied_at FROM schema_version WHERE version=2"
    ).fetchone()
    assert floor == "0.2.0"
    assert clock == format_instant(parse_instant(clock))
    assert receipt_guards.require_adoption_receipt_guards(conn)[
        "adoption_receipt_guards_ready"
    ]
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert migrations.migration_state(conn, running_version="0.1.0")["ready"] is False
    assert migrations.migration_state(conn, running_version="0.3.0")["ready"] is True
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("UPDATE migration_adoption_receipts SET recorded_at='changed'")
    conn.close()
    second = migrations.migrate(db_path=path, running_version="0.3.0")
    assert second["data"]["applied"] == []
    assert second["data"]["restore_point"] is None


@pytest.mark.parametrize(
    "bad", ["", "2026-10-09", "not a clock", 123, "2026-10-09T15:00:00-00:00"]
)
def test_invalid_stored_value_refuses_before_schema_write(tmp_path, bad):
    conn = _legacy_database(tmp_path / "invalid.db")
    conn.execute("UPDATE sessions SET expires_at=?", (bad,))
    conn.commit()
    before = list(conn.iterdump())
    traced = []
    conn.set_trace_callback(traced.append)
    with pytest.raises(InvalidInstant):
        migrations.apply_migration(
            conn, migrations.ordered_history()[1], running_version="0.2.0"
        )
    assert list(conn.iterdump()) == before
    assert not any(
        sql.startswith(("CREATE TABLE _instant", "DROP TABLE")) for sql in traced
    )
    conn.close()


@pytest.mark.parametrize(
    "dependency",
    [
        "CREATE INDEX custom_sessions ON sessions(expires_at)",
        "CREATE VIEW custom_sessions AS SELECT * FROM sessions",
        "CREATE TABLE custom_refs (user_id REFERENCES users(id))",
        "ALTER TABLE users ADD COLUMN custom TEXT",
    ],
)
def test_customized_dependency_refuses_without_mutation(tmp_path, dependency):
    conn = _legacy_database(tmp_path / "custom.db")
    conn.execute(dependency)
    conn.commit()
    before = list(conn.iterdump())
    with pytest.raises(RuntimeError, match="project-owned migration"):
        migrations.apply_migration(
            conn, migrations.ordered_history()[1], running_version="0.2.0"
        )
    assert list(conn.iterdump()) == before
    conn.close()


def test_conversion_accepts_its_output_without_losing_constraints(tmp_path):
    conn = _legacy_database(tmp_path / "repeat.db")
    conn.execute("BEGIN IMMEDIATE")
    conversion.apply(conn)
    conversion.invariants(conn)
    first = list(conn.iterdump())
    conversion.apply(conn)
    conversion.invariants(conn)
    assert list(conn.iterdump()) == first
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO sessions VALUES ('bad', 999, ?, ?)",
            (format_instant(INSTANT), None),
        )
    conn.rollback()
    conn.close()


def test_session_expiry_compares_native_microseconds(tmp_path, monkeypatch):
    path = tmp_path / "sessions.db"
    conn = _legacy_database(path)
    conn.close()
    migrations.migrate(db_path=path, running_version="0.2.0")
    monkeypatch.setenv("APP_DB_PATH", str(path))
    monkeypatch.setattr(auth, "utc_now", lambda: INSTANT)
    assert auth.validate_session("token")["name"] == OPAQUE
    conn = sqlite3.connect(path)
    conn.execute(
        "UPDATE sessions SET expires_at=?", ("2026-10-09T20:00:00.123456+05:00",)
    )
    conn.commit()
    assert auth.validate_session("token") is None
    token = auth.create_session(1)
    assert conn.execute(
        "SELECT created_at, expires_at FROM sessions WHERE id=?", (token,)
    ).fetchone() == ("2026-10-09T15:00:00.123456Z", "2026-10-16T15:00:00.123456Z")
    conn.execute("UPDATE sessions SET expires_at='' WHERE id=?", (token,))
    conn.commit()
    with pytest.raises(InvalidInstant):
        auth.validate_session(token)
    conn.close()


def test_tasks_keep_native_start_and_monotonic_duration_and_retention(monkeypatch):
    tick = [10.0]
    monkeypatch.setattr(runner.time, "monotonic", lambda: tick[0])
    monkeypatch.setattr(
        runner.time, "time", lambda: (_ for _ in ()).throw(AssertionError("wall clock"))
    )
    task = runner.TaskState(task_id="clock", stage="work", started_at=INSTANT)
    tick[0] = 12.3
    assert task.started_at is INSTANT
    assert task.to_dict()["started_at"] == "2026-10-09T15:00:00.123456Z"
    assert task.to_dict()["duration_s"] == 2.3
    task.complete({"text": OPAQUE})
    tick[0] = 4000.0
    assert task.to_dict()["duration_s"] == 2.3
    executor = runner.TaskRunner()
    executor.tasks = {task.task_id: task}
    executor._prune_old_tasks()
    assert executor.tasks == {}
    executor.shutdown()
    with pytest.raises(InvalidInstant):
        runner.TaskState(
            task_id="naive", stage="work", started_at=datetime(2026, 10, 9)
        )


def test_new_receipt_clock_is_canonical_with_historical_guards(tmp_path, monkeypatch):
    from utils import timestamps

    conn = _legacy_database(tmp_path / "receipt.db")
    monkeypatch.setattr(timestamps, "utc_now", lambda: INSTANT)
    manifest = {
        "manifest_sha256": "e" * 64,
        "artifact": {
            "engine_version": "0.2.0",
            "source_artifact": OPAQUE,
            "source_sha256": "f" * 64,
            "source_commit": "a" * 40,
        },
    }
    receipt_guards.record_adoption_receipt(
        conn,
        manifest,
        [{"name": "sample", "opaque": OPAQUE}],
        "operator",
        {"verifier": "verified", "verification_receipt_sha256": "b" * 64},
    )
    row = conn.execute(
        "SELECT source_artifact, adopted_entries_json, recorded_at "
        "FROM migration_adoption_receipts WHERE manifest_sha256=?",
        ("e" * 64,),
    ).fetchone()
    assert row[0] == OPAQUE
    assert OPAQUE in row[1]
    assert row[2] == "2026-10-09T15:00:00.123456Z"
    assert receipt_guards.require_adoption_receipt_guards(conn)[
        "adoption_receipt_guards_ready"
    ]
    conn.close()


def test_naive_generated_session_clock_refuses_before_connection(monkeypatch):
    monkeypatch.setattr(auth, "utc_now", lambda: datetime(2026, 10, 9))
    monkeypatch.setattr(
        auth,
        "get_connection",
        lambda: pytest.fail("database accessed before validation"),
    )
    with pytest.raises(InvalidInstant):
        auth.create_session(1)


def test_born_sqlite_clock_defaults_and_constraints(tmp_path):
    path = tmp_path / "born.db"
    migrations.migrate(db_path=path, running_version="0.2.0")
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(
        "INSERT INTO users (email, password_hash) VALUES ('sample@example.test', 'opaque')"
    )
    clock = conn.execute("SELECT created_at FROM users").fetchone()[0]
    assert clock == format_instant(parse_instant(clock))
    for name, clocks in conversion.CLOCKS.items():
        info = {row[1]: row[2] for row in conn.execute(f"PRAGMA table_info({name})")}
        assert all(info[clock] == "TEXT" for clock in clocks)
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        conn.execute(
            "INSERT INTO users (email, password_hash) VALUES ('sample@example.test', 'opaque')"
        )
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        conn.execute(
            "INSERT INTO users (email, password_hash, role) VALUES ('other@example.test', 'opaque', 'invalid')"
        )
    conn.close()
