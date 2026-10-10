"""Full Doctor fixture schemas preserve native clocks and nullable slim state."""

from datetime import datetime, timedelta

import pytest

from yoke_contracts.timestamps import parse_instant

NOW = parse_instant("2060-10-08T00:00:00.123456Z")
OPAQUE = "2060-10-08T00:00:00+09:00 unchanged"


@pytest.mark.parametrize("zone", ["UTC", "America/Los_Angeles", "Asia/Kathmandu"])
@pytest.mark.parametrize("audit_owner", ["shared", "dispatch"])
def test_full_doctor_catalog_clocks_and_audit_rows_are_native(zone, audit_owner):
    from runtime.api.engines import _doctor_hc_meta_full_test_helpers as fixtures
    from yoke_core.domain.stored_instant_columns import STORED_INSTANT_COLUMNS

    conn = fixtures._make_conn()
    try:
        conn.execute("SELECT set_config('TimeZone', %s, true)", (zone,))
        if audit_owner == "dispatch":
            from runtime.api.engines.test_doctor_hc_meta_full_dispatch import (
                _ensure_migration_audit_table,
            )
        else:
            _ensure_migration_audit_table = fixtures._ensure_migration_audit_table
        _ensure_migration_audit_table(conn)
        catalog = {
            (row[0], row[1]): (row[2], row[3])
            for row in conn.execute(
                "SELECT table_name, column_name, data_type, is_nullable "
                "FROM information_schema.columns WHERE table_schema='public'"
            ).fetchall()
        }
        declared = set(STORED_INSTANT_COLUMNS) & set(catalog)
        assert len(declared) >= 34
        assert all(catalog[key][0] == "timestamp with time zone" for key in declared)
        assert catalog["items", "created_at"][1] == "YES"
        assert catalog["items", "spec_updated_at"][1] == "YES"
        assert catalog["migration_audit", "started_at"][1] == "NO"
        assert catalog["migration_audit", "completed_at"][1] == "YES"
        conn.execute(
            "INSERT INTO items (id, title, created_at, updated_at) VALUES (1, %s, %s, %s)",
            (OPAQUE, NOW, NOW),
        )
        conn.execute(
            "INSERT INTO migration_audit (id, migration_name, tables_declared, "
            "expected_deltas, pre_row_counts, backup_path, started_at, rehearsed_at) "
            "VALUES (1, %s, '[]', '{}', '{}', %s, %s, %s)",
            (OPAQUE, OPAQUE, NOW, NOW),
        )
        row = conn.execute(
            "SELECT started_at, rehearsed_at, completed_at, migration_name, backup_path "
            "FROM migration_audit WHERE id=1"
        ).fetchone()
        assert all(
            isinstance(clock, datetime) and clock == NOW and clock.microsecond == 123456
            for clock in row[:2]
        )
        assert row[2] is None and row[3] == row[4] == OPAQUE
        row = conn.execute(
            "SELECT created_at, updated_at, spec_updated_at, title FROM items WHERE id=1"
        ).fetchone()
        assert row[0] == row[1] == NOW and row[2] is None and row[3] == OPAQUE
    finally:
        conn.close()


def test_full_doctor_generators_keep_microseconds(monkeypatch):
    from runtime.api.engines import _doctor_hc_meta_full_test_helpers as fixtures

    monkeypatch.setattr(fixtures, "utc_now", lambda: NOW)
    assert fixtures._instant_days_ago(2) == NOW - timedelta(days=2)
    assert fixtures._instant_minutes_ago(3) == NOW - timedelta(minutes=3)
    assert isinstance(fixtures._NOW_INSTANT, datetime)
    assert fixtures._NOW_INSTANT.utcoffset() is not None
    monkeypatch.setattr(fixtures, "utc_now", lambda: datetime(2060, 10, 8))
    with pytest.raises(ValueError):
        fixtures._instant_days_ago(1)
    with pytest.raises(ValueError):
        fixtures._instant_minutes_ago(1)
