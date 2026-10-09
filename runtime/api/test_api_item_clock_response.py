"""Item response clocks format native database facts at their wire owner."""

from datetime import datetime, timedelta

import pytest

from runtime.api.api_items_test_helpers import (
    connect_test_db,
    make_test_db_fixture,
)
from yoke_contracts.timestamps import format_instant, parse_instant
from yoke_core.api.main_route_adapters import _row_to_item

MOMENT = parse_instant("2026-10-09T15:56:12.345678+05:45")


@pytest.fixture()
def item_database():
    yield from make_test_db_fixture()


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kathmandu"])
def test_item_response_formats_native_clocks_and_preserves_null(item_database, zone):
    conn = connect_test_db(item_database["db_path"])
    try:
        conn.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
        conn.execute(
            "UPDATE items SET created_at=%s,updated_at=%s,merged_at=%s WHERE id=1",
            (MOMENT, MOMENT + timedelta(microseconds=1), MOMENT),
        )
        row = conn.execute("SELECT * FROM items WHERE id=1").fetchone()
        assert isinstance(row["created_at"], datetime)
        response = _row_to_item(row, conn=conn).model_dump()
        assert response["created_at"] == format_instant(MOMENT)
        assert response["updated_at"] == format_instant(
            MOMENT + timedelta(microseconds=1)
        )
        assert response["merged_at"] == format_instant(MOMENT)
        assert row["created_at"] == MOMENT
        absent = dict(row)
        absent["merged_at"] = None
        assert _row_to_item(absent, conn=conn).merged_at is None
    finally:
        conn.close()


@pytest.mark.parametrize("field", ["created_at", "updated_at", "merged_at"])
@pytest.mark.parametrize(
    "value",
    ["", "2026-02-30T10:11:12Z", "2026-10-09T10:11:12", MOMENT.replace(tzinfo=None)],
)
def test_item_response_refuses_malformed_declared_clock(item_database, field, value):
    conn = connect_test_db(item_database["db_path"])
    try:
        row = dict(conn.execute("SELECT * FROM items WHERE id=1").fetchone())
        row[field] = value
        with pytest.raises((ValueError, TypeError)):
            _row_to_item(row, conn=conn)
    finally:
        conn.close()
