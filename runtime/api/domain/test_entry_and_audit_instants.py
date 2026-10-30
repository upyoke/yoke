"""Entry CLI ingress and exception audit SQL retain native instants."""

from datetime import datetime

import pytest

from yoke_contracts.timestamps import parse_instant
from yoke_core.domain import migration_harness_audit as audit
from yoke_core.domain import ouroboros as entries
from yoke_core.domain.migration_audit_schema import ensure_migration_audit_table

MOMENT = parse_instant("2026-10-09T15:56:12.345678+05:45")
ZONES = ["UTC", "America/New_York", "Asia/Kathmandu"]
def test_legacy_entry_writer_is_unavailable():
    assert not hasattr(entries, "cmd_insert_entry")
    assert not hasattr(entries, "_insert_entry_named")


class BorrowedConnection:
    def __init__(self, conn):
        self._conn = conn

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def close(self):
        pass


def _audit(test_db, monkeypatch):
    ensure_migration_audit_table(test_db)
    monkeypatch.setattr(
        audit.db_backend, "connect", lambda *_args: BorrowedConnection(test_db)
    )
    return audit.record_audit_fingerprint(
        "disposable-validation",
        "Clock fingerprint",
        "Native exception evidence",
        [],
        {},
        {},
        exception_reason="Fixture verifies the documented no-backup audit path",
    )


@pytest.mark.parametrize("zone", ZONES)
def test_exception_audit_binds_native_instants_in_any_database_timezone(
    test_db, monkeypatch, zone
):
    test_db.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    monkeypatch.setattr(audit, "utc_now", lambda: MOMENT)
    assert _audit(test_db, monkeypatch) == ""
    row = test_db.execute(
        "SELECT started_at,completed_at FROM migration_audit WHERE migration_name='Clock fingerprint'"
    ).fetchone()
    assert tuple(row) == (MOMENT, MOMENT)
    assert isinstance(row[0], datetime)


def test_exception_audit_refuses_naive_internal_clock_before_insert(
    test_db, monkeypatch
):
    monkeypatch.setattr(audit, "utc_now", lambda: MOMENT.replace(tzinfo=None))
    with pytest.raises(ValueError):
        _audit(test_db, monkeypatch)
    assert (
        test_db.execute(
            "SELECT COUNT(*) FROM migration_audit WHERE migration_name='Clock fingerprint'"
        ).fetchone()[0]
        == 0
    )
