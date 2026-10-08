"""Fleet persistence and pagination retain exact instants across boundaries."""

import base64
from datetime import datetime, timedelta, timezone

import pytest

from yoke_contracts.timestamps import InvalidInstant, format_instant
from yoke_core.domain.json_helper import dumps_compact
from yoke_core.domain.session_message_cursor import (
    decode_message_cursor,
    encode_message_cursor,
)
from yoke_core.domain.session_message_page import _select_ids, read_message_page
from yoke_core.domain.session_message_service import send_message
from yoke_core.domain.session_message_store import insert_message
from yoke_core.domain.session_message_types import SessionMessageError, parse_timestamp
from runtime.api.domain.test_session_message_support import (
    NOW,
    message_connection,
    selector,
)


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kolkata"])
def test_native_message_write_and_cursor_keep_microseconds(test_db, zone):
    test_db.execute("SELECT set_config('TimeZone', %s, true)", (zone,))
    instant = datetime(
        1969,
        12,
        31,
        18,
        29,
        59,
        123456,
        tzinfo=timezone(timedelta(hours=-5, minutes=-30)),
    )
    actor_id = test_db.execute(
        "INSERT INTO actors (kind,name,created_at) VALUES (%s,%s,%s) RETURNING id",
        ("human", "Message writer", instant),
    ).fetchone()[0]
    message, inserted = insert_message(
        test_db,
        sender_actor_id=actor_id,
        sender_session_id=None,
        sender_surface="cli",
        body="native instant",
        selector_snapshot={},
        idempotency_key=None,
        created_at=instant,
        expires_at=instant + timedelta(hours=1),
        recipients=[],
        actor_recipients=[],
        wake_after_by_project={},
    )
    assert inserted
    actual, kind = test_db.execute(
        "SELECT created_at,pg_typeof(created_at)::text FROM session_messages WHERE message_id=%s",
        (message["message_id"],),
    ).fetchone()
    assert kind == "timestamp with time zone"
    assert actual == instant
    assert message["created_at"] == "1969-12-31T23:59:59.123456Z"
    assert message["cancelled_at"] is None
    selected = _select_ids(test_db, ["m.message_id=%s"], [message["message_id"]])
    assert selected == [(message["message_id"], instant)]
    cursor = encode_message_cursor(selected[0][1], selected[0][0])
    assert decode_message_cursor(cursor) == (instant, message["message_id"])


def test_message_pages_order_microseconds_then_equal_instant_ids(monkeypatch):
    from yoke_core.domain import session_message_delivery, session_message_page

    monkeypatch.setattr(session_message_delivery, "utc_now", lambda: NOW)
    monkeypatch.setattr(session_message_page, "utc_now", lambda: NOW)
    conn = message_connection()
    expected = []
    for microsecond in (123455, 123456, 123456, 123457):
        instant = NOW.replace(microsecond=microsecond)
        message = send_message(
            conn,
            actor_id=10,
            sender_session_id="s2",
            selector=selector(session_ids=["s3"]),
            body="equal instant",
            now=instant,
        )
        message_id = message["message_id"]
        conn.execute(
            "UPDATE session_message_recipients SET state='acknowledged',acknowledged_at=? WHERE message_id=?",
            (format_instant(instant), message_id),
        )
        conn.commit()
        expected.append((instant, message_id))
    actual = []
    cursor = None
    for _ in range(4):
        page = read_message_page(
            conn,
            actor_id=10,
            caller_session_id="s2",
            projects=[2],
            cursor=cursor,
            limit=1,
        )
        actual.extend(row["message_id"] for row in page["messages"])
        cursor = page["next_cursor"]
    assert actual == [message_id for _, message_id in sorted(expected, reverse=True)]
    assert cursor is None


@pytest.mark.parametrize(
    "payload",
    [
        {"created_at": "2026-10-08T00:00:00Z", "message_id": "m"},
        {"v": 1, "created_at": "2026-10-08T00:00:00Z", "message_id": "m"},
        {"v": 1, "created_at": "2026-10-08T01:00:00.000000+01:00", "message_id": "m"},
        {"v": True, "created_at": "2026-10-08T00:00:00.000000Z", "message_id": "m"},
        {"v": 1, "created_at": None, "message_id": "m"},
    ],
)
def test_obsolete_or_noncanonical_message_cursor_requires_clear(payload):
    cursor = (
        base64.urlsafe_b64encode(dumps_compact(payload).encode()).decode().rstrip("=")
    )
    with pytest.raises(SessionMessageError, match="clear it") as caught:
        decode_message_cursor(cursor)
    assert caught.value.code == "cursor_invalid"


@pytest.mark.parametrize(
    "value", ["", "2026-10-08", "2026-10-08T00:00:00", 0, datetime(2026, 10, 8)]
)
def test_optional_message_instant_does_not_hide_invalid_state(value):
    with pytest.raises(InvalidInstant, match="invalid_instant"):
        parse_timestamp(value)
    assert parse_timestamp(None) is None
