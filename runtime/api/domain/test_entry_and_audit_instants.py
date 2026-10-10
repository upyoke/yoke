"""Entry CLI ingress and exception audit SQL retain native instants."""

from datetime import datetime

import pytest

from yoke_contracts.timestamps import parse_instant
from yoke_core.domain import migration_harness_audit as audit
from yoke_core.domain import ouroboros as entries
from yoke_core.domain.migration_audit_schema import ensure_migration_audit_table

MOMENT = parse_instant("2026-10-09T15:56:12.345678+05:45")
ZONES = ["UTC", "America/New_York", "Asia/Kathmandu"]
ARGS = [
    "--agent",
    "clock-reader",
    "--category",
    "observation",
    "--observation",
    "Opaque 2026-10-09 10:11:12+00:00",
]


@pytest.mark.parametrize("supplied", [None, "2026-10-09T15:56:12.345678+05:45"])
def test_named_entry_forwards_native_clock_and_opaque_evidence(monkeypatch, supplied):
    seen = []
    monkeypatch.setattr(entries, "utc_now", lambda: MOMENT)
    monkeypatch.setattr(
        entries, "cmd_insert_entry", lambda *args: seen.append(args) or 1
    )
    args = ARGS + ([] if supplied is None else ["--timestamp", supplied])
    entries._insert_entry_named(object(), args)
    assert seen[0][1] == MOMENT
    assert isinstance(seen[0][1], datetime)
    assert seen[0][5] == ARGS[-1]


@pytest.mark.parametrize(
    "value", ["", "2026-10-09", "2026-02-30T10:11:12Z", "2026-10-09T10:11:12"]
)
def test_named_entry_invalid_supplied_clock_refuses_before_writer(monkeypatch, value):
    monkeypatch.setattr(
        entries, "cmd_insert_entry", lambda *_args: pytest.fail("entry write")
    )
    with pytest.raises(ValueError):
        entries._insert_entry_named(object(), ARGS + ["--timestamp", value])


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
