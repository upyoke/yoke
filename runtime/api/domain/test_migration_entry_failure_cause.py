"""A failed entry must report what actually broke, not what broke last.

An entry that crosses a guard restores it in a ``finally``. On Postgres the
statement that really failed aborts the transaction, so the restore in the
``finally`` fails too — with a generic "transaction is aborted" — and that
replaces the real error. One live outage was diagnosed from a report showing
exactly that: the traceback named the ``finally`` line and the exception type
carried no information, while the unique-constraint violation that caused it
survived only on ``__context__``.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from yoke_core.domain.migration_boot_apply import (
    EntryFailed,
    _failure_reason,
    apply_pending,
)
from yoke_core.domain.migration_audit_schema import (
    ensure_applied_migrations_table,
    ensure_migration_audit_table,
)
from yoke_core.domain.migration_history import ordered_entries

RESTORE_POINT = "snapshot:test-restore-point"

#: An entry shaped like the ones in the real history: it crosses a guard,
#: fails inside the guarded region, and its cleanup fails on the way out.
MASKED_FAILURE_ENTRY = (
    "def apply(conn):\n"
    "    try:\n"
    "        raise ValueError('the real cause')\n"
    "    finally:\n"
    "        raise RuntimeError('cleanup could not run')\n"
)

INVARIANT_FAILURE_ENTRY = (
    "def apply(conn):\n"
    "    pass\n"
    "\n"
    "def invariants(conn):\n"
    "    try:\n"
    "        raise ValueError('the invariant that failed')\n"
    "    finally:\n"
    "        raise RuntimeError('cleanup could not run')\n"
)


def _connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    ensure_applied_migrations_table(conn)
    ensure_migration_audit_table(conn)
    conn.commit()
    return conn


def _history(tmp_path: Path, name: str, body: str):
    (tmp_path / f"{name}.py").write_text(body)
    return ordered_entries(tmp_path)


def _receipt_reason(conn: sqlite3.Connection) -> str:
    return conn.execute(
        "SELECT failure_reason FROM migration_audit ORDER BY id DESC LIMIT 1"
    ).fetchone()[0]


class TestFailureReason:
    def test_names_the_root_of_a_chain(self) -> None:
        try:
            try:
                raise ValueError("the real cause")
            finally:
                raise RuntimeError("cleanup could not run")
        except RuntimeError as exc:
            reason = _failure_reason(exc)

        assert "the real cause" in reason
        assert "ValueError" in reason
        assert "RuntimeError" in reason, "the surfaced type stays visible too"

    def test_an_unchained_exception_reads_as_itself(self) -> None:
        reason = _failure_reason(ValueError("plain"))

        assert reason == "ValueError: plain"
        assert "surfaced as" not in reason

    def test_a_self_referential_chain_terminates(self) -> None:
        """A cycle would otherwise walk forever."""
        first = ValueError("first")
        second = RuntimeError("second")
        first.__context__ = second
        second.__context__ = first

        assert "first" in _failure_reason(first) or "second" in _failure_reason(first)


class TestApplyFailure:
    def test_raises_naming_the_root_cause(self, tmp_path: Path) -> None:
        conn = _connection()
        history = _history(tmp_path, "0001_masked", MASKED_FAILURE_ENTRY)

        with pytest.raises(EntryFailed, match="the real cause"):
            apply_pending(
                conn,
                history=history,
                applied_by="test",
                running_version="",
                external_restore_point=RESTORE_POINT,
            )

    def test_names_the_entry_that_failed(self, tmp_path: Path) -> None:
        conn = _connection()
        history = _history(tmp_path, "0001_masked", MASKED_FAILURE_ENTRY)

        with pytest.raises(EntryFailed, match="0001_masked"):
            apply_pending(
                conn,
                history=history,
                applied_by="test",
                running_version="",
                external_restore_point=RESTORE_POINT,
            )

    def test_receipt_records_the_root_cause(self, tmp_path: Path) -> None:
        # The receipt is what an operator reads after the container is gone.
        conn = _connection()
        history = _history(tmp_path, "0001_masked", MASKED_FAILURE_ENTRY)

        with pytest.raises(EntryFailed):
            apply_pending(
                conn,
                history=history,
                applied_by="test",
                running_version="",
                external_restore_point=RESTORE_POINT,
            )

        assert "the real cause" in _receipt_reason(conn)

    def test_a_failing_invariant_reports_its_own_cause(self, tmp_path: Path) -> None:
        conn = _connection()
        history = _history(tmp_path, "0001_invariant", INVARIANT_FAILURE_ENTRY)

        with pytest.raises(EntryFailed, match="the invariant that failed"):
            apply_pending(
                conn,
                history=history,
                applied_by="test",
                running_version="",
                external_restore_point=RESTORE_POINT,
            )

        assert "the invariant that failed" in _receipt_reason(conn)
