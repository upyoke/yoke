"""Durable landing observation and exactly-once fleet notification."""

from __future__ import annotations

from types import SimpleNamespace

from runtime.api.domain.test_session_message_support import NOW, message_connection
from yoke_core.domain.merge_queue_landing_pending import observe_pending_landings


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
        ALTER TABLE harness_sessions ADD COLUMN actor_id INTEGER;
        UPDATE harness_sessions SET actor_id=10;
        UPDATE items SET merge_queue_pr_number='42',
          merge_queue_enqueued_at='2026-08-27T17:00:00Z' WHERE id=101;
        """
    )
    conn.commit()
    return conn


def _merged(_ctx, _pr_number):
    return SimpleNamespace(merged=True), None


def test_landing_notification_is_sent_once_to_the_claim_holder():
    conn = _connection()

    first = observe_pending_landings(conn, [1], now=NOW, read_state=_merged)
    second = observe_pending_landings(conn, [1], now=NOW, read_state=_merged)

    assert first == {"checked": 1, "landed": 1, "notified": 1, "unrouted": 0}
    assert second["notified"] == 0
    messages = conn.execute(
        "SELECT message_id,body FROM session_messages "
        "WHERE idempotency_key='merge-queue-landed:101:42'"
    ).fetchall()
    assert len(messages) == 1
    assert "Landing complete for ALP-1" in messages[0][1]
    recipient = conn.execute(
        "SELECT session_id FROM session_message_recipients WHERE message_id=?",
        (messages[0][0],),
    ).fetchone()
    assert recipient[0] == "s1"
    marker = conn.execute(
        "SELECT merge_queue_landed_at,merge_queue_notified_at FROM items WHERE id=101"
    ).fetchone()
    assert marker[0] and marker[1]


def test_missing_holder_routes_the_landing_to_steering():
    conn = _connection()
    conn.execute("UPDATE work_claims SET released_at='2026-08-27T17:30:00Z'")
    conn.execute(
        "INSERT INTO work_claims "
        "(id,session_id,target_kind,scope,claimed_at) VALUES "
        "(99,'s4','steering','{\"project_id\":1}','2026-08-27T17:31:00Z')"
    )
    conn.commit()

    result = observe_pending_landings(conn, [1], now=NOW, read_state=_merged)

    assert result["notified"] == 1
    row = conn.execute(
        "SELECT r.session_id,m.body FROM session_message_recipients r "
        "JOIN session_messages m ON m.message_id=r.message_id "
        "WHERE m.idempotency_key='merge-queue-landed:101:42'"
    ).fetchone()
    assert row[0] == "s4"
    assert "claim holder is gone" in row[1]
