"""Native event storage, fractional ranges and canonical cursor boundaries."""

import base64
import json
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from yoke_contracts.timestamps import InvalidInstant, format_instant, parse_instant
from yoke_core.domain.events import build_envelope
from yoke_core.domain.events_history_read import decode_cursor, encode_cursor
from yoke_core.domain.events_relative_time import parse_since
from yoke_core.domain.events_write_conn import (
    event_insert_params,
    write_event_row_on_conn,
)
from yoke_core.domain.events_insert_sql import _INSERT_SQL
from yoke_core.domain import performance_query


def test_event_envelope_is_canonical_and_insert_parameters_are_native():
    envelope = build_envelope(
        "YokeFunctionCalled",
        event_kind="operation",
        event_type="function",
        created_at="2026-10-08T12:00:00.123456-04:00",
    )
    assert envelope["created_at"] == "2026-10-08T16:00:00.123456Z"
    params = event_insert_params(envelope, None)
    assert params[-1] == parse_instant(envelope["created_at"])
    assert params[-1].tzinfo is timezone.utc
    assert json.loads(params[-2])["created_at"] == envelope["created_at"]


@pytest.mark.parametrize(
    "value", ["", "2026-10-08", "2026-10-08T00:00:00", "2026-02-29T00:00:00Z"]
)
def test_invalid_event_and_range_instants_refuse(value):
    with pytest.raises(InvalidInstant):
        build_envelope(
            "YokeFunctionCalled",
            event_kind="operation",
            event_type="function",
            created_at=value,
        )
    with pytest.raises(ValueError):
        parse_since(value)


def test_event_cursor_retains_microseconds_and_refuses_old_tokens():
    value = parse_instant("2026-10-08T12:00:00.123456-04:00")
    assert decode_cursor(encode_cursor(value, 9)) == (value, 9)
    old = base64.urlsafe_b64encode(
        json.dumps({"created_at": "2026-10-08T16:00:00Z", "id": 9}).encode()
    ).decode()
    with pytest.raises(ValueError, match="predates.*clear it"):
        decode_cursor(old)


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kolkata"])
def test_performance_fractional_half_open_range_uses_native_event_instants(
    test_db, monkeypatch, zone
):
    monkeypatch.setattr(
        performance_query, "authorized_predicate", lambda *args: ("TRUE", [])
    )
    test_db.execute("SELECT set_config('TimeZone', %s, true)", (zone,))
    prefix = str(uuid4())
    for micros in [0, 499999, 500000, 500001, 999999]:
        stamp = datetime(2026, 10, 8, 12, microsecond=micros, tzinfo=timezone.utc)
        envelope = build_envelope(
            "YokeFunctionCalled",
            event_kind="operation",
            event_type="function",
            session_id=prefix,
            duration_ms=1,
            created_at=format_instant(stamp),
        )
        assert write_event_row_on_conn(
            test_db, _INSERT_SQL, event_insert_params(envelope, None)
        )
    start = parse_instant("2026-10-08T12:00:00.500000Z")
    end = parse_instant("2026-10-08T12:00:00.999999Z")
    result = performance_query.read_observations(test_db, None, None, start, end)
    ours = [row for row in result if row["session_id"] == prefix]
    assert [row["observed_at"] for row in ours] == [
        format_instant(start),
        "2026-10-08T12:00:00.500001Z",
    ]
    type_row = test_db.execute(
        "SELECT pg_typeof(created_at)::text FROM events WHERE session_id=%s LIMIT 1",
        (prefix,),
    ).fetchone()
    assert type_row[0] == "timestamp with time zone"
