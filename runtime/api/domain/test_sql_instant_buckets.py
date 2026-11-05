"""UTC SQL buckets are zone independent; guard their SQL expressions only."""

import pytest

from runtime.api.fixtures.session_zones import SESSION_ZONES
from runtime.sql_calendar_guard import unsafe_buckets

from yoke_contracts.timestamps import parse_instant
from yoke_core.engines.doctor_hc_db_events_ledger import (
    _day_bucket_sql,
    _week_bucket_sql,
)


@pytest.mark.parametrize("zone", SESSION_ZONES)
@pytest.mark.parametrize(
    "wire,day,week",
    [
        ("2026-01-01T00:00:00.000001Z", "2026-01-01", "2026-01"),
        ("2026-10-04T23:59:59.999999Z", "2026-10-04", "2026-40"),
        ("2026-10-05T00:00:00.000000Z", "2026-10-05", "2026-41"),
    ],
)
def test_ledger_bucket_results_are_utc(test_db, zone, wire, day, week):
    test_db.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    sql = f"SELECT {_day_bucket_sql('point')}, {_week_bucket_sql('point')} "
    row = test_db.execute(
        sql + "FROM (SELECT %s::timestamptz AS point) input", (parse_instant(wire),)
    ).fetchone()
    assert tuple(row) == (day, week)


def test_sql_scan_rejects_a_planted_violation_before_execution(test_db):
    with pytest.raises(AssertionError, match="sql_instant_bucket_session_zone"):
        test_db.execute("SELECT date_trunc('day', now())")


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT to_char(created_at, 'YYYY-MM-DD') FROM events",
        "SELECT to_char(created_at, 'DD') FROM events",
        "SELECT (created_at AT TIME ZONE 'UTC'), updated_at::date FROM events",
        "SELECT created_at:: date FROM events",
        "SELECT date_trunc('day', created_at) FROM events",
        "SELECT created_at::date FROM events",
        "SELECT to_char(created_at, 'YYYY-MM-DD'), "
        "to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD') FROM events",
    ],
)
def test_sql_scan_rejects_planted_session_zone_buckets(sql):
    assert unsafe_buckets(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD') FROM events",
        "SELECT date_trunc('day', created_at AT TIME ZONE 'UTC') FROM events",
        "SELECT (created_at AT TIME ZONE 'UTC')::date FROM events",
        "SELECT to_char(count, '999') FROM totals",
    ],
)
def test_sql_scan_accepts_utc_calendar_and_numeric_expressions(sql):
    assert not unsafe_buckets(sql)
