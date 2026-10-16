"""Replay proof runs on the governed copy and retains the fleet checks."""

from __future__ import annotations

import importlib
import json
import sqlite3
from unittest.mock import Mock

import pytest

from runtime.api.tools import migration_rehearsal_secret_receipts as replay
from runtime.api.tools import yoke_migration_fleet as fleet
from yoke_core.domain.function_call_ledger import record_call
from yoke_core.domain.migration_restore_point import RESTORE_POINT_ENV


SECRET = "fixture-only-secret-do-not-report"


def _entry():
    return importlib.import_module(f"yoke_core.domain.migrations.{replay.ENTRY_NAME}")


@pytest.fixture
def copy():
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        "CREATE TABLE function_call_ledger "
        "(request_id TEXT PRIMARY KEY, function_id TEXT, result TEXT);"
        "CREATE TABLE events (id INTEGER PRIMARY KEY, event_name TEXT, envelope TEXT);"
    )
    conn.execute(
        "INSERT INTO function_call_ledger VALUES ('original', 'profile.token.create', ?)",
        (json.dumps({"raw_token": SECRET}),),
    )
    conn.execute(
        "INSERT INTO events VALUES (1, 'UnrelatedEvent', ?)",
        (' {"preserve": "exact bytes"} ',),
    )
    conn.commit()
    try:
        yield conn
    finally:
        conn.close()


def test_replay_uses_same_connection_and_only_emits_counts(copy, monkeypatch, capsys):
    _entry().apply(copy)
    capsys.readouterr()
    apply = Mock(wraps=_entry().apply)
    monkeypatch.setattr(_entry(), "apply", apply)
    before = replay._receipts(copy)

    assert replay.verify_secret_receipt_replay(copy) is None

    apply.assert_called_once_with(copy)
    assert replay._receipts(copy) == before
    assert capsys.readouterr().out == (
        "admission_secret_receipts_replay ledger_rows_rewritten=0 "
        "event_envelopes_rewritten=0 ledger_rows_checked=1 event_envelopes_checked=1\n"
    )


def test_postgres_cursor_covers_native_receipt_values(test_db, capsys):
    record_call(
        "rehearsal-receipt", "profile.token.create", {"raw_token": SECRET},
        actor_id="fixture", authorization_scope="global", payload_checksum="request",
        conn=test_db,
    )
    _entry().apply(test_db)
    capsys.readouterr()
    assert replay.verify_secret_receipt_replay(test_db) is None
    assert "ledger_rows_checked=1" in capsys.readouterr().out


def test_unscrubbed_copy_refuses_before_replay(copy, monkeypatch, capsys):
    apply = Mock()
    monkeypatch.setattr(_entry(), "apply", apply)
    assert replay.verify_secret_receipt_replay(copy).startswith("secret_receipt_replay_failed")
    apply.assert_not_called()
    assert SECRET not in capsys.readouterr().out


@pytest.mark.parametrize("damage", ("bytes", "identity", "count", "exception"))
def test_replay_refuses_changes_and_never_echoes_failure_payloads(
    copy, monkeypatch, capsys, damage,
):
    _entry().apply(copy)
    capsys.readouterr()

    def apply(conn):
        if damage == "exception":
            print(SECRET)
            raise ValueError(SECRET)
        if damage == "bytes":
            conn.execute("UPDATE events SET envelope = ?", (SECRET,))
        elif damage == "identity":
            conn.execute("UPDATE events SET id = 2")
        print(replay.ZERO_COUNTS.replace("=0", "=1") if damage == "count" else replay.ZERO_COUNTS, end="")

    monkeypatch.setattr(_entry(), "apply", apply)
    failure = replay.verify_secret_receipt_replay(copy)
    assert failure.startswith("secret_receipt_replay_failed")
    output = capsys.readouterr()
    assert SECRET not in failure + output.out + output.err


@pytest.mark.parametrize("failed_check", (None, "replay", "readers", "release"))
def test_fleet_callback_preserves_order_and_refusals(monkeypatch, failed_check):
    from runtime.api.tools import migration_rehearsal_readers

    seen = []
    conn, dsn = object(), "fixture-copy"

    def check(name):
        def run(current, *args):
            assert current is conn
            assert args == (() if name == "replay" else (dsn,))
            seen.append(name)
            return "refused" if name == failed_check else None
        return run

    monkeypatch.setattr(replay, "verify_secret_receipt_replay", check("replay"))
    monkeypatch.setattr(migration_rehearsal_readers, "verify_migrated_readers", check("readers"))
    monkeypatch.setattr(fleet, "verify_migrated_release_surfaces", check("release"))
    assert fleet.rehearsal_plan().post_converge_validator is fleet.verify_migrated_copy
    assert fleet.verify_migrated_copy(conn, dsn) == ("refused" if failed_check else None)
    checks = ["replay", "readers", "release"]
    expected = checks[:checks.index(failed_check) + 1] if failed_check else checks
    assert seen == expected


@pytest.mark.parametrize("binding", ("missing", "mismatch", "archive-missing", "archive-empty"))
def test_entrypoint_requires_verified_bindings_and_archive(monkeypatch, tmp_path, binding, capsys):
    archive = tmp_path / "validation.sql"
    archive.write_text("baseline")
    monkeypatch.setenv("YOKE_DB", "fixture-validation")
    monkeypatch.setenv("YOKE_PG_DSN", "fixture-validation")
    monkeypatch.setenv(RESTORE_POINT_ENV, str(archive))
    if binding == "missing":
        monkeypatch.delenv("YOKE_DB")
    elif binding == "mismatch":
        monkeypatch.setenv("YOKE_PG_DSN", "different")
    elif binding == "archive-missing":
        archive.unlink()
    else:
        archive.write_text("")
    connect = Mock()
    monkeypatch.setattr(replay.db_backend, "connect_psycopg", connect)
    assert replay.main() == 1
    connect.assert_not_called()
    assert "fixture-validation" not in capsys.readouterr().out


@pytest.mark.parametrize("failure", (False, True))
def test_entrypoint_binds_exact_copy_and_rolls_back_failed_proof(
    copy, monkeypatch, tmp_path, failure,
):
    archive = tmp_path / "validation.sql"
    archive.write_text("baseline")
    monkeypatch.setenv("YOKE_DB", "fixture-validation")
    monkeypatch.setenv("YOKE_PG_DSN", "fixture-validation")
    monkeypatch.setenv(RESTORE_POINT_ENV, str(archive))
    targets = []
    monkeypatch.setattr(
        replay.db_backend, "connect_psycopg", lambda target: targets.append(target) or copy,
    )

    def verify(conn):
        assert conn is copy
        conn.execute("UPDATE events SET envelope = 'changed'")
        return "secret_receipt_replay_failed" if failure else None

    monkeypatch.setattr(replay, "verify_secret_receipt_replay", verify)
    assert replay.main() == int(failure)
    assert targets == ["fixture-validation"]
    assert copy.execute("SELECT envelope FROM events").fetchone()[0] == (
        ' {"preserve": "exact bytes"} ' if failure else "changed"
    )
