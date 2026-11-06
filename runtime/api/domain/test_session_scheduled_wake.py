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
    schedule_session_wake,
    enqueue_due_session_wakes,
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
