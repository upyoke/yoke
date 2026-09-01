"""Durable landing observation, push wake, and delivery-stamped notify."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

from runtime.api.domain.test_session_message_support import NOW, message_connection
from yoke_contracts.session_control.wake import EXPLICIT_WAKE_ROUTING_FLAG
from yoke_core.domain.merge_queue_landing_pending import observe_pending_landings

INJECTED_AT = datetime(2026, 8, 27, 17, 5, tzinfo=timezone.utc)
INJECTED_TEXT = "2026-08-27T17:05:00Z"


def _connection():
    conn = message_connection()
    conn.executescript(
        """
        ALTER TABLE items ADD COLUMN status TEXT DEFAULT 'reviewing-implementation';
        ALTER TABLE items ADD COLUMN merged_at TEXT;
        ALTER TABLE items ADD COLUMN merge_queue_pr_number TEXT;
        ALTER TABLE items ADD COLUMN merge_queue_enqueued_at TEXT;
        ALTER TABLE items ADD COLUMN merge_queue_landed_at TEXT;
        ALTER TABLE items ADD COLUMN merge_queue_notified_at TEXT;
        UPDATE harness_sessions SET actor_id=10;
        UPDATE items SET merge_queue_pr_number='42',
          merge_queue_enqueued_at='2026-08-27T17:00:00Z' WHERE id=101;
        """
    )
    conn.commit()
    return conn


def _merged(_ctx, _pr_number):
    return SimpleNamespace(merged=True), None


def _queued_message_id(conn) -> str:
    row = conn.execute(
        "SELECT message_id FROM session_messages "
        "WHERE idempotency_key='merge-queue-landed:101:42'"
    ).fetchone()
    assert row is not None
    return str(row[0])


def _inject(conn, message_id: str) -> None:
    conn.execute(
        "UPDATE session_message_recipients SET state='injected', "
        "injection_count=1, last_injected_at=? WHERE message_id=?",
        (INJECTED_TEXT, message_id),
    )
    conn.commit()


def test_landing_notification_is_sent_once_to_the_claim_holder():
    conn = _connection()

    queued = observe_pending_landings(conn, [1], now=NOW, read_state=_merged)
    assert queued == {"checked": 1, "landed": 1, "notified": 0, "unrouted": 0}

    message_id = _queued_message_id(conn)
    body = conn.execute(
        "SELECT body FROM session_messages WHERE message_id=?", (message_id,)
    ).fetchone()[0]
    assert "Landing complete for ALP-1" in body
    recipient = conn.execute(
        "SELECT session_id, routing_snapshot FROM session_message_recipients "
        "WHERE message_id=?",
        (message_id,),
    ).fetchone()
    assert recipient[0] == "s1"
    snapshot = json.loads(str(recipient[1]))
    assert snapshot[EXPLICIT_WAKE_ROUTING_FLAG] is True
    marker = conn.execute(
        "SELECT merge_queue_landed_at,merge_queue_notified_at FROM items WHERE id=101"
    ).fetchone()
    assert marker[0]
    assert marker[1] is None

    _inject(conn, message_id)
    delivered = observe_pending_landings(conn, [1], now=INJECTED_AT, read_state=_merged)
    assert delivered["notified"] == 1
    assert delivered["landed"] == 0
    second = observe_pending_landings(conn, [1], now=INJECTED_AT, read_state=_merged)
    assert second["notified"] == 0
    messages = conn.execute(
        "SELECT message_id FROM session_messages "
        "WHERE idempotency_key='merge-queue-landed:101:42'"
    ).fetchall()
    assert len(messages) == 1
    notified = conn.execute(
        "SELECT merge_queue_landed_at,merge_queue_notified_at FROM items WHERE id=101"
    ).fetchone()
    assert notified[0] != notified[1]


def test_missing_holder_routes_the_landing_to_steering():
    conn = _connection()
    conn.execute("UPDATE work_claims SET released_at='2026-08-27T17:30:00Z'")
    conn.execute(
        "INSERT INTO work_claims "
        "(id,session_id,target_kind,scope,claimed_at) VALUES "
        "(99,'s4','steering','{\"project_id\":1}','2026-08-27T17:31:00Z')"
    )
    conn.commit()

    queued = observe_pending_landings(conn, [1], now=NOW, read_state=_merged)
    assert queued["notified"] == 0
    row = conn.execute(
        "SELECT r.session_id,m.body FROM session_message_recipients r "
        "JOIN session_messages m ON m.message_id=r.message_id "
        "WHERE m.idempotency_key='merge-queue-landed:101:42'"
    ).fetchone()
    assert row[0] == "s4"
    assert "claim holder is gone" in row[1]
    _inject(conn, _queued_message_id(conn))
    delivered = observe_pending_landings(conn, [1], now=INJECTED_AT, read_state=_merged)
    assert delivered["notified"] == 1


def test_ended_holder_still_receives_the_landing_push():
    conn = _connection()
    conn.execute(
        "UPDATE harness_sessions SET ended_at='2026-08-27T17:02:00Z' "
        "WHERE session_id='s1'"
    )
    conn.commit()

    queued = observe_pending_landings(conn, [1], now=NOW, read_state=_merged)
    assert queued["unrouted"] == 0
    assert queued["notified"] == 0
    recipient = conn.execute(
        "SELECT session_id FROM session_message_recipients r "
        "JOIN session_messages m ON m.message_id=r.message_id "
        "WHERE m.idempotency_key='merge-queue-landed:101:42'"
    ).fetchone()
    assert recipient[0] == "s1"
