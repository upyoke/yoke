"""A start that arrives after its own completion still becomes the start.

Observations reach the database in bounded, retried batches, so a call's
opening observation can land after the completion that closed it. The
completion writes a placeholder row stamped at its own instant; these tests
cover what happens when the genuine start turns up afterwards — it corrects
that one endpoint, and it corrects nothing else.
"""

from __future__ import annotations

import pytest

from runtime.api.fixtures.session_holdings import insert_session
from yoke_core.domain.session_activity_state import (
    record_tool_call_finished,
    record_tool_call_started,
)


SESSION_ID = "reordered-worker"
CALL_ID = "call-late-start"
STARTED = "2026-09-08T12:00:00.000Z"
COMPLETED = "2026-09-08T12:00:01.500Z"


@pytest.fixture
def worker(test_db):
    insert_session(test_db, SESSION_ID)
    test_db.commit()
    return test_db


def _start(conn, *, at: str, session_id: str = SESSION_ID, call: str = CALL_ID):
    return record_tool_call_started(
        conn,
        session_id=session_id,
        tool_use_id=call,
        tool_name="Read",
        started_at=at,
    )


def _complete(conn, *, at: str, session_id: str = SESSION_ID, call: str = CALL_ID):
    return record_tool_call_finished(
        conn,
        session_id=session_id,
        tool_use_id=call,
        tool_name="Read",
        event_name="HarnessToolCallCompleted",
        outcome="completed",
        completed_at=at,
    )


def _call(conn, *, session_id: str = SESSION_ID, call: str = CALL_ID) -> dict:
    row = conn.execute(
        "SELECT started_at, completed_at, outcome FROM session_tool_calls "
        "WHERE session_id = %s AND tool_use_id = %s",
        (session_id, call),
    ).fetchone()
    return dict(row)


def _activity(conn) -> dict:
    row = conn.execute(
        "SELECT last_tool_call_at, tool_call_count FROM harness_sessions "
        "WHERE session_id = %s",
        (SESSION_ID,),
    ).fetchone()
    return dict(row)


def test_a_start_arriving_after_its_completion_replaces_the_placeholder(worker):
    """The completion's own instant is a placeholder, not a captured start."""
    _complete(worker, at=COMPLETED)
    assert _call(worker)["started_at"] == COMPLETED

    assert _start(worker, at=STARTED) is True
    worker.commit()

    call = _call(worker)
    assert call["started_at"] == STARTED
    assert call["completed_at"] == COMPLETED


def test_reconciling_a_late_start_never_reopens_the_call(worker):
    """A corrected endpoint must not turn finished work back into running."""
    _complete(worker, at=COMPLETED)
    _start(worker, at=STARTED)
    worker.commit()

    call = _call(worker)
    assert call["completed_at"] == COMPLETED
    assert call["outcome"] == "completed"


def test_a_late_start_does_not_count_the_call_a_second_time(worker):
    """Activity is counted by the completion, whatever order things arrive."""
    _complete(worker, at=COMPLETED)
    _start(worker, at=STARTED)
    worker.commit()

    activity = _activity(worker)
    assert activity["tool_call_count"] == 1
    assert activity["last_tool_call_at"] == COMPLETED


def test_both_arrival_orders_record_the_same_pair_of_endpoints(worker):
    """Ordering is a delivery accident; the stored call must not show it."""
    _start(worker, at=STARTED)
    _complete(worker, at=COMPLETED)
    in_order = _call(worker)

    _complete(worker, at=COMPLETED, call="reordered-call")
    _start(worker, at=STARTED, call="reordered-call")
    worker.commit()
    reordered = _call(worker, call="reordered-call")

    assert reordered["started_at"] == in_order["started_at"] == STARTED
    assert reordered["completed_at"] == in_order["completed_at"] == COMPLETED


def test_a_replayed_start_changes_nothing(worker):
    """A redelivered start carries the instant it always carried."""
    _complete(worker, at=COMPLETED)
    _start(worker, at=STARTED)
    worker.commit()

    assert _start(worker, at=STARTED) is False
    worker.commit()

    assert _call(worker)["started_at"] == STARTED
    assert _activity(worker)["tool_call_count"] == 1


def test_a_duplicate_start_never_moves_the_start_forwards(worker):
    """Two starts for one call: the earlier one is when the call began."""
    _start(worker, at=STARTED)
    assert _start(worker, at=COMPLETED) is False
    worker.commit()

    assert _call(worker)["started_at"] == STARTED


def test_an_unreadable_arriving_start_leaves_the_stored_one_alone(worker):
    """A timestamp nobody can read is not evidence about when work began."""
    _start(worker, at=STARTED)

    assert _start(worker, at="not-a-timestamp") is False
    worker.commit()

    assert _call(worker)["started_at"] == STARTED


def test_a_valid_start_replaces_an_unreadable_stored_one(worker):
    """An unreadable stored start is a gap a real capture should fill."""
    _start(worker, at="not-a-timestamp")

    assert _start(worker, at=STARTED) is True
    worker.commit()

    assert _call(worker)["started_at"] == STARTED


def test_reconciliation_stays_inside_the_calls_own_session(worker):
    """A tool-use id is unique only within its session."""
    other_session = "neighbouring-worker"
    insert_session(worker, other_session)
    _complete(worker, at=COMPLETED, session_id=other_session)
    _start(worker, at=STARTED)
    worker.commit()

    assert _call(worker, session_id=other_session)["started_at"] == COMPLETED
    assert _call(worker)["started_at"] == STARTED


def test_reconciliation_holds_where_telemetry_is_not_retained(worker):
    """Whether a deployment keeps events is not a fact about the call."""
    worker.execute("DROP TABLE events")
    worker.commit()

    _complete(worker, at=COMPLETED)
    assert _start(worker, at=STARTED) is True
    worker.commit()

    call = _call(worker)
    assert call["started_at"] == STARTED
    assert call["completed_at"] == COMPLETED
    assert _activity(worker)["tool_call_count"] == 1
