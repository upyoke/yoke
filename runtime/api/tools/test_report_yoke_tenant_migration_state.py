"""Yoke tenant reports distinguish current evidence from attempt history."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from runtime.api.tools import report_yoke_tenant_migration_state as report


class _Cursor:
    def __init__(self):
        self.query = ""

    def execute(self, query, _params=None):
        self.query = query

    def fetchone(self):
        if "to_regclass('applied_migrations')" in self.query:
            return ("applied_migrations",)
        if "information_schema.columns" in self.query:
            return (True,)
        if "to_regclass('migration_audit')" in self.query:
            return ("migration_audit",)
        raise AssertionError(self.query)

    def fetchall(self):
        if "FROM applied_migrations" in self.query:
            return [("0001_first", "now", "boot", "2.0.0")]
        if "FROM migration_audit" in self.query:
            if "DISTINCT ON" in self.query:
                return [
                    ("0001_first", "completed", "later"),
                    ("0002_second", "live_apply_failed", "latest"),
                ]
            if "SELECT DISTINCT migration_name" in self.query:
                return [("0001_first",)]
            return [("completed", 1, "later"), ("live_apply_failed", 3, "old")]
        raise AssertionError(self.query)


def test_ledger_reader_includes_serving_floor() -> None:
    assert report._ledger(_Cursor()) == [
        ("0001_first", "now", "boot", "2.0.0")
    ]


def test_audit_reader_preserves_historical_attempt_counts() -> None:
    assert report._audit_attempts(_Cursor()) == [
        ("completed", 1, "later"), ("live_apply_failed", 3, "old")
    ]


def test_latest_outcomes_separate_resolved_from_unresolved_attempts() -> None:
    assert report._latest_audit_outcomes(_Cursor()) == [
        ("0001_first", "completed", "later"),
        ("0002_second", "live_apply_failed", "latest"),
    ]


def test_completed_receipts_are_compared_to_ledger_membership() -> None:
    assert report._completed_receipt_names(_Cursor()) == {"0001_first"}
    rows = [
        ("0001_first", "now", "boot", "2.0.0"),
        ("0002_second", "later", "boot", "3.0.0"),
    ]
    assert report._ledger_rows_without_completed_evidence(
        rows, {"0001_first"},
    ) == ["0002_second"]


def test_content_evidence_state_reports_adoption_and_mismatch_names(
    monkeypatch,
) -> None:
    status = SimpleNamespace(
        verified=("0001_first",),
        adoption_required=("0002_second",),
        mismatches=(SimpleNamespace(entry_name="0003_third"),),
        ledger_ahead=("0004_future",),
    )
    monkeypatch.setattr(
        report, "yoke_migration_content_schema_is_prepared", lambda _conn: True
    )
    monkeypatch.setattr(
        report, "migration_content_identity_status", lambda *_args: status
    )

    assert report._content_evidence_state(object(), ()) == {
        "prepared": True,
        "verified": ["0001_first"],
        "adoption_required": ["0002_second"],
        "mismatches": ["0003_third"],
        "ledger_ahead": ["0004_future"],
    }


def test_content_evidence_state_fails_closed_without_error_detail(monkeypatch) -> None:
    def unreadable(_conn):
        raise RuntimeError("dsn=must-not-leak")

    monkeypatch.setattr(
        report, "yoke_migration_content_schema_is_prepared", unreadable
    )
    state = report._content_evidence_state(object(), ())
    assert state["prepared"] is False
    assert state["mismatches"] == ["migration content evidence is unreadable"]


class _InvariantConnection:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def execute(self, statement: str) -> None:
        self.statements.append(statement)


def _passes(_conn: Any) -> None:
    return None


def _fails(_conn: Any) -> None:
    raise AssertionError("snapshot is incomplete\nfor delivery 7")


def test_packaged_pending_is_history_minus_ledger() -> None:
    checks = [("0001_first", _passes), ("0002_second", _passes)]

    assert report._packaged_pending(checks, {"0001_first"}) == ["0002_second"]


def test_applied_invariants_are_isolated_and_fail_closed() -> None:
    conn = _InvariantConnection()
    checks = [
        ("0001_first", _passes),
        ("0002_second", _fails),
        ("0003_third", None),
        ("0004_pending", _passes),
    ]

    assert report._applied_invariant_outcomes(
        conn, checks, {"0001_first", "0002_second", "0003_third"},
    ) == [
        ("0001_first", "passed", None),
        (
            "0002_second",
            "failed",
            "AssertionError: snapshot is incomplete for delivery 7",
        ),
        ("0003_third", "not_declared", None),
    ]
    assert conn.statements == [
        "SAVEPOINT yoke_report_migration_invariant",
        "RELEASE SAVEPOINT yoke_report_migration_invariant",
        "SAVEPOINT yoke_report_migration_invariant",
        "ROLLBACK TO SAVEPOINT yoke_report_migration_invariant",
        "RELEASE SAVEPOINT yoke_report_migration_invariant",
    ]
