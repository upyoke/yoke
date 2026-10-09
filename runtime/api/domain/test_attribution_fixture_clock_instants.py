"""Attribution fixtures retain SQL microseconds and explicit SQLite wire clocks."""

from datetime import datetime
import sqlite3

import pytest

from yoke_contracts.timestamps import format_instant, parse_instant

NOW = parse_instant("2060-10-08T00:00:00.123456Z")
OPAQUE = "2060-10-08T00:00:00+09:00 unchanged"


@pytest.mark.parametrize("zone", ["UTC", "America/Los_Angeles", "Asia/Kathmandu"])
def test_attribution_seed_clocks_are_native_on_real_authority(
    test_db, monkeypatch, zone
):
    from runtime.api.domain import observe_test_helpers as fixtures

    monkeypatch.setattr(fixtures, "utc_now", lambda: NOW)
    test_db.execute("SELECT set_config('TimeZone', %s, true)", (zone,))
    item_id = test_db.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM items").fetchone()[
        0
    ]
    fixtures.seed_item(test_db, item_id, status="idea")
    fixtures.seed_session(
        test_db,
        OPAQUE,
        current_item_id=OPAQUE,
        current_item_set_at="2060-10-08T05:45:00.123456+05:45",
    )
    row = test_db.execute(
        "SELECT offered_at, last_heartbeat, current_item_set_at, "
        "recent_item_recorded_at, current_item_id FROM harness_sessions "
        "WHERE session_id=%s",
        (OPAQUE,),
    ).fetchone()
    assert all(
        isinstance(v, datetime) and v == NOW and v.microsecond == 123456
        for v in row[:3]
    )
    assert row[3] is None and row[4] == OPAQUE
    item = test_db.execute(
        "SELECT created_at, updated_at FROM items WHERE id=%s", (item_id,)
    ).fetchone()
    assert all(
        isinstance(v, datetime) and v == parse_instant("2026-01-01T00:00:00Z")
        for v in item
    )
    assert fixtures._fresh_now() is NOW


@pytest.mark.parametrize("field", ["current_item_set_at", "recent_item_recorded_at"])
@pytest.mark.parametrize(
    "invalid", ["", "2060-10-08", "2060-10-08T00:00:00", 0, datetime(2060, 10, 8)]
)
def test_supplied_attribution_clock_refuses_before_sql(field, invalid):
    from runtime.api.domain import observe_test_helpers as fixtures

    with pytest.raises(ValueError):
        fixtures.seed_session(object(), OPAQUE, **{field: invalid})


def test_naive_attribution_generator_refuses_before_sql(monkeypatch):
    from runtime.api.domain import observe_test_helpers as fixtures

    monkeypatch.setattr(fixtures, "utc_now", lambda: datetime(2060, 10, 8))
    with pytest.raises(ValueError):
        fixtures.seed_session(object(), OPAQUE)


def test_sqlite_session_boundary_is_canonical_and_preserves_null(monkeypatch):
    from runtime.api.domain import observe_test_helpers as fixtures

    monkeypatch.setattr(fixtures, "utc_now", lambda: NOW)
    with sqlite3.connect(":memory:") as conn:
        conn.execute(
            "CREATE TABLE harness_sessions (session_id TEXT, executor TEXT, provider TEXT, "
            "model TEXT, workspace TEXT, offered_at TEXT, last_heartbeat TEXT, "
            "current_item_id TEXT, current_item_set_at TEXT, recent_item_id TEXT, "
            "recent_item_recorded_at TEXT)"
        )
        fixtures.seed_session(
            conn, OPAQUE, recent_item_id=OPAQUE, recent_item_recorded_at=NOW
        )
        row = conn.execute(
            "SELECT offered_at, last_heartbeat, recent_item_recorded_at, "
            "current_item_set_at, recent_item_id FROM harness_sessions"
        ).fetchone()
        assert row[:3] == (format_instant(NOW),) * 3
        assert row[3] is None and row[4] == OPAQUE
