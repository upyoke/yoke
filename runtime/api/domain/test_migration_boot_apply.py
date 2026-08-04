"""Coverage for boot-time apply of the pending migration history."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from yoke_core.domain.migration_boot_apply import (
    applied_names,
    apply_pending,
    pending_entries,
    stamp_history,
)
from yoke_core.domain.migration_audit_receipts import now_stamp, record_missing_receipts
from yoke_core.domain.migration_audit_schema import (
    ensure_applied_migrations_table,
    ensure_migration_audit_table,
)
from yoke_core.domain.migration_restore_point import RestorePointRequired
from yoke_core.domain.migration_history import ordered_entries

RESTORE_POINT = "snapshot:test-restore-point"


def _connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    # The real DDL, not a convenient subset of it. A hand-rolled table here
    # once omitted three NOT NULL columns the live schema has, so the receipt
    # assertions below passed against a shape no database actually has while
    # every receipt failed its constraint in production.
    ensure_applied_migrations_table(conn)
    ensure_migration_audit_table(conn)
    conn.execute("CREATE TABLE marks (name TEXT)")
    conn.commit()
    return conn


def _history(tmp_path: Path, *names: str, failing: str | None = None):
    """Build a history whose entries each record that they ran."""
    for name in names:
        body = (
            "def apply(conn):\n"
            f"    conn.execute(\"INSERT INTO marks VALUES ('{name}')\")\n"
        )
        if name == failing:
            body += "    raise RuntimeError('entry failed')\n"
        (tmp_path / f"{name}.py").write_text(body)
    return ordered_entries(tmp_path)


def _heal(conn: sqlite3.Connection, history) -> tuple[str, ...]:
    return record_missing_receipts(
        conn,
        history,
        applied=applied_names(conn),
        stamp=now_stamp(),
        restore_point=RESTORE_POINT,
    )


def _marks(conn: sqlite3.Connection) -> list[str]:
    return [row[0] for row in conn.execute("SELECT name FROM marks").fetchall()]


def test_pending_is_history_minus_ledger(tmp_path: Path) -> None:
    conn = _connection()
    history = _history(tmp_path, "0001_first", "0002_second", "0003_third")
    conn.execute(
        "INSERT INTO applied_migrations "
        "(migration_name, applied_at, applied_by) "
        "VALUES ('0001_first', 'now', 'test')"
    )

    assert [e.name for e in pending_entries(conn, history)] == [
        "0002_second",
        "0003_third",
    ]


def test_ledger_ahead_of_packaged_history_is_current(tmp_path: Path) -> None:
    # A rolled-back container runs older code than its database has applied.
    # Membership by name calls that current; head equality would call it
    # broken and refuse to serve, bricking the rollback direction too.
    conn = _connection()
    history = _history(tmp_path, "0001_first")
    conn.executemany(
        "INSERT INTO applied_migrations "
        "(migration_name, applied_at, applied_by) VALUES (?, 'now', 'test')",
        [("0001_first",), ("0002_from_newer_code",)],
    )

    assert pending_entries(conn, history) == ()


def test_apply_runs_entries_in_order_and_records_them(tmp_path: Path) -> None:
    conn = _connection()
    history = _history(tmp_path, "0001_first", "0002_second")

    outcome = apply_pending(
        conn,
        history=history,
        applied_by="test",
        external_restore_point=RESTORE_POINT,
    )

    assert outcome.applied == ("0001_first", "0002_second")
    assert outcome.changed is True
    assert _marks(conn) == ["0001_first", "0002_second"]
    assert applied_names(conn) == {"0001_first", "0002_second"}


def test_apply_is_a_no_op_when_current(tmp_path: Path) -> None:
    conn = _connection()
    history = _history(tmp_path, "0001_first")
    apply_pending(
        conn,
        history=history,
        applied_by="test",
        external_restore_point=RESTORE_POINT,
    )

    outcome = apply_pending(
        conn,
        history=history,
        applied_by="test",
        external_restore_point=RESTORE_POINT,
    )

    assert outcome.applied == ()
    assert outcome.changed is False
    assert _marks(conn) == ["0001_first"], "a current database must not re-run"


def test_apply_only_runs_what_is_outstanding(tmp_path: Path) -> None:
    conn = _connection()
    history = _history(tmp_path, "0001_first", "0002_second")
    conn.execute(
        "INSERT INTO applied_migrations "
        "(migration_name, applied_at, applied_by) "
        "VALUES ('0001_first', 'now', 'test')"
    )

    outcome = apply_pending(
        conn,
        history=history,
        applied_by="test",
        external_restore_point=RESTORE_POINT,
    )

    assert outcome.applied == ("0002_second",)
    assert _marks(conn) == ["0002_second"]


def test_empty_history_needs_no_restore_point(tmp_path: Path) -> None:
    conn = _connection()

    outcome = apply_pending(conn, history=(), applied_by="test")

    assert outcome.applied == ()


def test_current_database_needs_no_restore_point(tmp_path: Path) -> None:
    # The cheap probe must come first: the overwhelming majority of boots
    # are current and must not pay for a dump or a lock.
    conn = _connection()
    history = _history(tmp_path, "0001_first")
    conn.execute(
        "INSERT INTO applied_migrations "
        "(migration_name, applied_at, applied_by) "
        "VALUES ('0001_first', 'now', 'test')"
    )

    outcome = apply_pending(conn, history=history, applied_by="test")

    assert outcome.applied == ()


def test_apply_refuses_without_a_restore_point(tmp_path: Path) -> None:
    conn = _connection()
    history = _history(tmp_path, "0001_first")

    with pytest.raises(RestorePointRequired, match="no restore point"):
        apply_pending(conn, history=history, applied_by="test")

    assert _marks(conn) == []


def test_apply_refuses_two_restore_points(tmp_path: Path) -> None:
    conn = _connection()
    history = _history(tmp_path, "0001_first")

    with pytest.raises(RestorePointRequired, match="not both"):
        apply_pending(
            conn,
            history=history,
            applied_by="test",
            backup_root=tmp_path / "backups",
            external_restore_point=RESTORE_POINT,
        )


def test_failed_entry_stops_the_chain_and_leaves_the_ledger_truthful(
    tmp_path: Path,
) -> None:
    conn = _connection()
    history = _history(
        tmp_path, "0001_first", "0002_bad", "0003_third", failing="0002_bad"
    )

    with pytest.raises(RuntimeError, match="entry failed"):
        apply_pending(
            conn,
            history=history,
            applied_by="test",
            external_restore_point=RESTORE_POINT,
        )

    # The failed entry is not recorded, and nothing after it ran.
    assert applied_names(conn) == {"0001_first"}
    assert _marks(conn) == ["0001_first"]
    assert [e.name for e in pending_entries(conn, history)] == [
        "0002_bad",
        "0003_third",
    ]


def test_failed_entry_writes_a_receipt_naming_the_restore_point(
    tmp_path: Path,
) -> None:
    conn = _connection()
    history = _history(tmp_path, "0001_bad", failing="0001_bad")

    with pytest.raises(RuntimeError):
        apply_pending(
            conn,
            history=history,
            applied_by="test",
            external_restore_point=RESTORE_POINT,
        )

    row = conn.execute(
        "SELECT state, backup_path FROM migration_audit "
        "WHERE migration_name='0001_bad'"
    ).fetchone()
    assert row is not None, "a failed apply must leave evidence"
    assert row[0] == "live_apply_failed"
    assert row[1] == RESTORE_POINT


def test_completed_apply_writes_a_receipt(tmp_path: Path) -> None:
    conn = _connection()
    history = _history(tmp_path, "0001_first")

    apply_pending(
        conn,
        history=history,
        applied_by="test",
        external_restore_point=RESTORE_POINT,
    )

    row = conn.execute(
        "SELECT state, backup_path FROM migration_audit "
        "WHERE migration_name='0001_first'"
    ).fetchone()
    assert row == ("completed", RESTORE_POINT)


def test_invariants_failure_fails_the_boot_but_keeps_the_ledger(
    tmp_path: Path,
) -> None:
    conn = _connection()
    (tmp_path / "0001_first.py").write_text(
        "def apply(conn):\n"
        "    conn.execute(\"INSERT INTO marks VALUES ('0001_first')\")\n"
        "def invariants(conn):\n"
        "    raise AssertionError('invariant broken')\n"
    )
    history = ordered_entries(tmp_path)

    with pytest.raises(AssertionError, match="invariant broken"):
        apply_pending(
            conn,
            history=history,
            applied_by="test",
            external_restore_point=RESTORE_POINT,
        )

    # The entry really did apply, so the ledger must say so — the ledger
    # records what happened, not whether we were happy about it.
    assert applied_names(conn) == {"0001_first"}


def test_stamp_records_the_history_without_running_it(tmp_path: Path) -> None:
    # A newborn database got its schema from current code, so every entry is
    # already true of it; running them would be a no-op at best.
    conn = _connection()
    history = _history(tmp_path, "0001_first", "0002_second")

    stamped = stamp_history(conn, history, applied_by="birth")

    assert stamped == ("0001_first", "0002_second")
    assert applied_names(conn) == {"0001_first", "0002_second"}
    assert _marks(conn) == [], "birth stamping must not execute any entry"
    assert pending_entries(conn, history) == ()


def test_missing_receipts_are_recorded_for_ledger_entries(tmp_path: Path) -> None:
    """A stamped database has ledger rows and no receipts -- the same shape a
    receipt write failure leaves behind."""
    conn = _connection()
    history = _history(tmp_path, "0001_first", "0002_second")
    stamp_history(conn, history, applied_by="test")
    assert conn.execute("SELECT count(*) FROM migration_audit").fetchone()[0] == 0

    healed = _heal(conn, history)

    assert healed == ("0001_first", "0002_second")
    rows = conn.execute(
        "SELECT migration_name, state, backup_path FROM migration_audit "
        "ORDER BY migration_name"
    ).fetchall()
    assert rows == [
        ("0001_first", "completed", RESTORE_POINT),
        ("0002_second", "completed", RESTORE_POINT),
    ]


def test_recording_receipts_twice_adds_nothing(tmp_path: Path) -> None:
    conn = _connection()
    history = _history(tmp_path, "0001_first")
    stamp_history(conn, history, applied_by="test")
    _heal(conn, history)

    assert _heal(conn, history) == ()
    assert conn.execute("SELECT count(*) FROM migration_audit").fetchone()[0] == 1


def test_unapplied_entries_get_no_receipt(tmp_path: Path) -> None:
    """Only the ledger authorizes a receipt; a pending entry never ran."""
    conn = _connection()
    history = _history(tmp_path, "0001_first", "0002_second")
    stamp_history(conn, history[:1], applied_by="test")

    assert _heal(conn, history) == ("0001_first",)
