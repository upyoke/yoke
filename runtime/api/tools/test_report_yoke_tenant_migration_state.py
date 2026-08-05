"""Yoke tenant reports distinguish current evidence from attempt history."""

from __future__ import annotations

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
