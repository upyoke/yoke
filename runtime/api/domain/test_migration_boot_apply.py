"""Coverage for boot-time apply of the pending migration history."""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.api.domain.migration_boot_test_helpers import (
    RESTORE_POINT,
    applied_names,
    apply_pending,
    connection as _connection,
    heal as _heal,
    history as _history,
    marks as _marks,
    pending_entries,
    stamp_history,
)
from yoke_core.domain.migration_boot_apply import EntryFailed
from yoke_core.domain.migration_restore_point import RestorePointRequired
from yoke_core.domain.migration_history import ordered_entries


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
        running_version="",
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
        running_version="",
        external_restore_point=RESTORE_POINT,
    )

    outcome = apply_pending(
        conn,
        history=history,
        applied_by="test",
        running_version="",
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
        running_version="",
        external_restore_point=RESTORE_POINT,
    )

    assert outcome.applied == ("0002_second",)
    assert _marks(conn) == ["0002_second"]


def test_empty_history_needs_no_restore_point(tmp_path: Path) -> None:
    conn = _connection()

    outcome = apply_pending(conn, history=(), applied_by="test", running_version="")

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

    outcome = apply_pending(
        conn, history=history, applied_by="test", running_version=""
    )

    assert outcome.applied == ()


def test_apply_refuses_without_a_restore_point(tmp_path: Path) -> None:
    conn = _connection()
    history = _history(tmp_path, "0001_first")

    with pytest.raises(RestorePointRequired, match="no restore point"):
        apply_pending(conn, history=history, applied_by="test", running_version="")

    assert _marks(conn) == []


def test_apply_refuses_two_restore_points(tmp_path: Path) -> None:
    conn = _connection()
    history = _history(tmp_path, "0001_first")

    with pytest.raises(RestorePointRequired, match="not both"):
        apply_pending(
            conn,
            history=history,
            applied_by="test",
            running_version="",
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

    with pytest.raises(EntryFailed, match="entry failed"):
        apply_pending(
            conn,
            history=history,
            applied_by="test",
            running_version="",
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

    with pytest.raises(EntryFailed):
        apply_pending(
            conn,
            history=history,
            applied_by="test",
            running_version="",
            external_restore_point=RESTORE_POINT,
        )

    row = conn.execute(
        "SELECT state, backup_path FROM migration_audit WHERE migration_name='0001_bad'"
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
        running_version="",
        external_restore_point=RESTORE_POINT,
    )

    row = conn.execute(
        "SELECT state, backup_path FROM migration_audit "
        "WHERE migration_name='0001_first'"
    ).fetchone()
    assert row == ("completed", RESTORE_POINT)


def test_invariants_failure_rolls_back_mutation_and_ledger(
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

    with pytest.raises(EntryFailed, match="invariant broken"):
        apply_pending(
            conn,
            history=history,
            applied_by="test",
            running_version="",
            external_restore_point=RESTORE_POINT,
        )

    assert applied_names(conn) == set()
    assert _marks(conn) == []
    row = conn.execute(
        "SELECT state FROM migration_audit WHERE migration_name='0001_first'"
    ).fetchone()
    assert row == ("live_verify_failed",)


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
