"""Each arming earns its own notice, and queued notices retain visibility."""

from dataclasses import replace

from runtime.api.domain.merge_queue_observer_test_helpers import (
    ARMED_AWAITING_CHECKS,
    INJECTED_AT,
    INJECTED_TEXT,
    armed_awaiting_checks,
    check_failed,
    ejected_message_id,
    inject,
    message_count,
    not_queued,
    observe,
    observer_connection,
)


def marker(conn):
    return conn.execute(
        "SELECT merge_queue_enqueued_at FROM items WHERE id=101"
    ).fetchone()[0]


def acknowledge(conn, message_id):
    inject(conn, message_id)
    conn.execute(
        "UPDATE session_message_recipients SET state='acknowledged', "
        "acknowledged_at=? WHERE message_id=?",
        (INJECTED_TEXT, message_id),
    )
    conn.commit()


def failed_checks(conn):
    return observe(
        conn,
        now=INJECTED_AT,
        read_state=armed_awaiting_checks,
        read_membership=not_queued,
        read_checks=check_failed,
    )


def test_disarm_then_rearm_same_commit_sends_a_second_notice():
    conn = observer_connection()
    original_episode = marker(conn)
    # Steering disarms the landing; the worker receives and reads that stop.
    disarmed = replace(ARMED_AWAITING_CHECKS, auto_merge_active=False)
    assert observe(conn, read_state=lambda *_: (disarmed, None))["ejected"] == 1
    first_id = ejected_message_id(conn)
    acknowledge(conn, first_id)
    conn.execute(
        "UPDATE items SET merge_queue_enqueued_at=? WHERE id=101",
        (INJECTED_TEXT,),
    )
    conn.commit()

    # The worker re-arms the unchanged head, whose required checks go red.
    assert failed_checks(conn)["ejected"] == 1
    assert message_count(conn) == 2
    rows = conn.execute(
        "SELECT m.message_id,m.idempotency_key,r.state "
        "FROM session_messages m JOIN session_message_recipients r "
        "ON m.message_id=r.message_id ORDER BY m.rowid"
    ).fetchall()
    assert original_episode in rows[0][1]
    second_id, second_key, state = rows[1]
    assert second_id != first_id
    assert INJECTED_TEXT in second_key
    assert state == "pending"
    assert marker(conn) == INJECTED_TEXT

    # Re-observation reuses the queued message and preserves the visible row.
    failed_checks(conn)
    assert message_count(conn) == 2
    assert marker(conn) == INJECTED_TEXT
    inject(conn, second_id)
    failed_checks(conn)
    assert marker(conn) is None
    assert failed_checks(conn)["ejected"] == 0
    assert message_count(conn) == 2


def test_an_acknowledged_dedupe_refuses_and_keeps_the_landing_visible():
    conn = observer_connection()
    episode = marker(conn)
    failed_checks(conn)
    message_id = ejected_message_id(conn)
    acknowledge(conn, message_id)

    observed = failed_checks(conn)

    assert observed["ejected"] == 0
    assert message_count(conn) == 1
    assert marker(conn) == episode
    error = observed["notice_errors"][0]
    assert error["item_id"] == 101
    assert error["pr_number"] == "42"
    assert "notice_already_acknowledged" in error["error"]
    assert message_id in error["error"]
    assert "re-enter yoke merge item" in error["error"]


def test_a_pending_notice_keeps_the_admission_until_injection():
    conn = observer_connection()
    episode = marker(conn)
    failed_checks(conn)
    failed_checks(conn)
    assert message_count(conn) == 1
    assert marker(conn) == episode

    inject(conn, ejected_message_id(conn))
    failed_checks(conn)
    assert marker(conn) is None
