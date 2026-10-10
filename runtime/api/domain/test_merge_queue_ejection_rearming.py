"""Each arming earns its own notice, and queued notices retain visibility."""

from dataclasses import replace
from types import SimpleNamespace

from yoke_contracts.timestamps import format_instant, parse_instant

from yoke_core.domain.merge_queue_landing_marker import point_item_at_pull_request
from yoke_core.domain.merge_queue_landing_pending import mark_landing_pending

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
    point_item_at_pull_request(conn, 101, "42", enqueued_at=INJECTED_TEXT)

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


def test_an_already_armed_retry_preserves_its_recorded_episode():
    writes = []
    episode = "2026-08-27T17:00:00Z"

    def dispatch(*, function_id, target, payload):
        if function_id == "items.detail.get":
            return SimpleNamespace(
                success=True,
                result={
                    "item": {
                        "merge_queue": {
                            "pr_number": "42",
                            "enqueued_at": episode,
                        }
                    }
                },
            )
        writes.append(payload)
        return SimpleNamespace(success=True, result=payload)

    assert mark_landing_pending(
        "ITEM-101",
        "42",
        dispatch=dispatch,
        now=INJECTED_AT,
        preserve_existing=True,
    ) == (parse_instant(episode), "")
    assert writes == [{"pr_number": "42", "enqueued_at": format_instant(episode)}]


def test_a_new_arming_does_not_reuse_an_existing_episode():
    writes = []

    def dispatch(*, function_id, target, payload):
        assert function_id == "merge_queue.landing_pending.mark"
        writes.append(payload)
        return SimpleNamespace(success=True, result=payload)

    assert mark_landing_pending(
        "ITEM-101",
        "42",
        dispatch=dispatch,
        now=INJECTED_AT,
    ) == (INJECTED_AT, "")
    assert writes == [{"pr_number": "42", "enqueued_at": INJECTED_TEXT}]


def test_an_unreadable_existing_episode_refuses_before_marking():
    calls = []

    def dispatch(*, function_id, target, payload):
        calls.append(function_id)
        return SimpleNamespace(success=False, error=SimpleNamespace(message="offline"))

    episode, error = mark_landing_pending(
        "ITEM-101",
        "42",
        dispatch=dispatch,
        now=INJECTED_AT,
        preserve_existing=True,
    )
    assert episode is None
    assert "landing_episode_unreadable" in error
    assert "offline" in error
    assert "re-enter yoke merge item" in error
    assert calls == ["items.detail.get"]


def test_two_armings_in_one_second_have_distinct_episode_timestamps():
    writes = []

    def dispatch(*, function_id, target, payload):
        writes.append(payload)
        return SimpleNamespace(success=True, result=payload)

    for microsecond in (1, 2):
        mark_landing_pending(
            "ITEM-101",
            "42",
            dispatch=dispatch,
            now=INJECTED_AT.replace(microsecond=microsecond),
        )
    assert writes[0]["enqueued_at"] != writes[1]["enqueued_at"]
