"""A durable recheck waits for its due instant through hooks and relay."""

from datetime import timedelta

import pytest

from runtime.api.domain.session_message_support_test_support import (
    NOW,
    message_connection,
)
from yoke_core.domain.session_message_delivery import _lease_candidates
from yoke_core.domain.session_message_types import SessionMessageError
from yoke_core.domain.session_message_wake import wake_eligible_recipients
from yoke_core.domain.session_scheduled_wake import (
    enqueue_due_session_wakes,
    next_session_wakes,
    pending_session_wake_holders,
    recheck_label,
    schedule_session_wake,
)


def test_timer_is_not_delivered_by_an_earlier_message_turn():
    conn = message_connection()
    due = NOW + timedelta(days=1)
    sent = schedule_session_wake(
        conn, session_id="s2", actor_id=10, at=due, reason="one day of traffic", now=NOW
    )
    conn.commit()
    assert _lease_candidates(conn, session_id="s2", now=NOW, limit=10) == []
    assert wake_eligible_recipients(conn, now=NOW) == []
    assert enqueue_due_session_wakes(conn, now=due) == 1
    rows = _lease_candidates(conn, session_id="s2", now=due, limit=10)
    message_id = conn.execute(
        "SELECT message_id FROM session_scheduled_wakes WHERE wake_id=?",
        (sent["wake_id"],),
    ).fetchone()[0]
    assert [row["message_id"] for row in rows] == [message_id]
    assert enqueue_due_session_wakes(conn, now=due) == 0
    assert "one day of traffic" in rows[0]["body"]
    repeated = schedule_session_wake(
        conn, session_id="s2", actor_id=10, at=due, reason="one day of traffic", now=NOW
    )
    assert repeated["deduplicated"] is True


def test_due_timer_takes_the_existing_native_wake_route():
    conn = message_connection()
    due = NOW + timedelta(hours=1)
    sent = schedule_session_wake(
        conn, session_id="s2", actor_id=10, at=due, reason="traffic recheck", now=NOW
    )
    conn.commit()
    eligible = wake_eligible_recipients(conn, now=due)
    message_id = conn.execute(
        "SELECT message_id FROM session_scheduled_wakes WHERE wake_id=?",
        (sent["wake_id"],),
    ).fetchone()[0]
    assert [row["message_id"] for row in eligible] == [message_id]


def test_past_timer_refuses_with_recovery():
    with pytest.raises(SessionMessageError, match="future --at"):
        schedule_session_wake(
            message_connection(),
            session_id="s2",
            actor_id=10,
            at=NOW,
            reason="traffic",
            now=NOW,
        )


def test_due_timer_is_consumed_once_on_postgres(test_db):
    from runtime.api.domain.deployment_qa_stage_wake_delivery_test_support import (
        HOLDER_A,
        _project,
        seed_session,
    )
    from yoke_contracts.timestamps import utc_now

    _project(test_db)
    seed_session(test_db, HOLDER_A)
    now = utc_now()
    due = now + timedelta(minutes=1)
    sent = schedule_session_wake(
        test_db,
        session_id=HOLDER_A,
        actor_id=1,
        at=due,
        reason="traffic recheck",
        now=now,
    )
    assert enqueue_due_session_wakes(test_db, now=now) == 0
    assert enqueue_due_session_wakes(test_db, now=due) == 1
    assert enqueue_due_session_wakes(test_db, now=due) == 0
    assert test_db.execute(
        "SELECT message_id FROM session_scheduled_wakes WHERE wake_id=%s",
        (sent["wake_id"],),
    ).fetchone()[0]


def test_next_wakes_are_each_sessions_earliest_pending_future_due():
    conn = message_connection()
    for session_id, minutes in (("s2", 30), ("s2", 40), ("s2", 180), ("s2", 60)):
        schedule_session_wake(
            conn,
            session_id=session_id,
            actor_id=10,
            at=NOW + timedelta(minutes=minutes),
            reason=f"recheck {minutes}",
            now=NOW,
        )
    schedule_session_wake(
        conn,
        session_id="s1",
        actor_id=10,
        at=NOW + timedelta(hours=2),
        reason="recheck s1",
        now=NOW,
    )
    # The 30-minute row is consumed; at +50m the 40-minute row is past.
    assert enqueue_due_session_wakes(conn, now=NOW + timedelta(minutes=30)) == 1
    conn.commit()
    query = NOW + timedelta(minutes=50)

    wakes = next_session_wakes(conn, ("s1", "s2", "s3", ""), now=query)

    assert wakes == {
        "s2": NOW + timedelta(minutes=60),
        "s1": NOW + timedelta(hours=2),
    }
    assert pending_session_wake_holders(conn, ("s1", "s2", "s3"), now=query) == {
        "s1",
        "s2",
    }
    assert next_session_wakes(conn, (), now=query) == {}


def test_recheck_label_prefixes_the_day_only_when_it_is_not_today():
    due = NOW + timedelta(hours=2)
    assert recheck_label(due, now=NOW) == "18:00Z"
    assert recheck_label(due + timedelta(days=1), now=NOW) == "08-23 18:00Z"
