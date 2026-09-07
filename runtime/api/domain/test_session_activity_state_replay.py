"""Activity accounting survives replay, reordering, and absent telemetry.

The resident retries a batch whose later observation failed, so the earlier
ones arrive again — sometimes long after the ``events`` rows they were
written beside have been pruned, and not always in the order they happened.
Every assertion here is about what remains true when telemetry is gone,
because telemetry going is the ordinary case rather than the failure.
"""

from __future__ import annotations

import pytest

from runtime.api.fixtures.session_holdings import insert_session
from yoke_core.domain.session_activity_state import (
    record_tool_call_finished,
    record_tool_call_started,
)
from yoke_core.domain.session_recovery_facts import PROMISED_WORK_HOLDS_TABLE


SESSION_ID = "replaying-worker"
CALL_ID = "call-1"
EARLIER = "2026-09-03T20:00:00Z"
LATER = "2026-09-03T20:00:05Z"


@pytest.fixture
def worker(test_db):
    insert_session(test_db, SESSION_ID)
    test_db.commit()
    return test_db


def _activity(conn) -> dict:
    row = conn.execute(
        "SELECT last_tool_call_at, tool_call_count, first_completed_work_at, "
        "last_completed_work_at FROM harness_sessions WHERE session_id = %s",
        (SESSION_ID,),
    ).fetchone()
    return dict(row)


def _complete(conn, *, at: str, event_name: str = "HarnessToolCallCompleted") -> bool:
    return record_tool_call_finished(
        conn,
        session_id=SESSION_ID,
        tool_use_id=CALL_ID,
        tool_name="Bash",
        event_name=event_name,
        outcome="completed",
        completed_at=at,
    )


def test_a_replayed_completion_counts_exactly_once(worker):
    record_tool_call_started(
        worker,
        session_id=SESSION_ID,
        tool_use_id=CALL_ID,
        tool_name="Bash",
        started_at=EARLIER,
    )

    assert _complete(worker, at=LATER) is True
    assert _complete(worker, at=LATER) is False
    worker.commit()

    assert _activity(worker)["tool_call_count"] == 1


def test_replay_after_the_telemetry_row_is_gone_still_counts_once(worker):
    """Deduplication is the call identity, not the surviving event row.

    Suppressing a replay on ``events`` existence meant the suppression
    expired with the row, and the same observation then reapplied itself.
    """
    record_tool_call_started(
        worker,
        session_id=SESSION_ID,
        tool_use_id=CALL_ID,
        tool_name="Bash",
        started_at=EARLIER,
    )
    _complete(worker, at=LATER)
    worker.execute("DELETE FROM events WHERE session_id = %s", (SESSION_ID,))
    worker.commit()

    assert _complete(worker, at=LATER) is False
    worker.commit()

    assert _activity(worker)["tool_call_count"] == 1


def test_a_reordered_replay_never_moves_activity_backwards(worker):
    """An older stamp landing late would manufacture idleness.

    ``last_tool_call_at`` is what the idle sweep, claim freshness, and the
    vendor-resume budget all read, so a backwards move restaffs a working
    session's item.
    """
    record_tool_call_started(
        worker,
        session_id=SESSION_ID,
        tool_use_id=CALL_ID,
        tool_name="Bash",
        started_at=EARLIER,
    )
    _complete(worker, at=LATER)
    record_tool_call_started(
        worker,
        session_id=SESSION_ID,
        tool_use_id="call-0",
        tool_name="Bash",
        started_at=EARLIER,
    )
    record_tool_call_finished(
        worker,
        session_id=SESSION_ID,
        tool_use_id="call-0",
        tool_name="Bash",
        event_name="HarnessToolCallCompleted",
        outcome="completed",
        completed_at=EARLIER,
    )
    worker.commit()

    activity = _activity(worker)
    assert activity["last_tool_call_at"] == LATER
    assert activity["tool_call_count"] == 2


def test_completed_work_markers_bracket_the_calls_that_actually_completed(worker):
    """Launch settlement reads these long after the call rows are pruned."""
    record_tool_call_started(
        worker,
        session_id=SESSION_ID,
        tool_use_id=CALL_ID,
        tool_name="Bash",
        started_at=EARLIER,
    )
    _complete(worker, at=EARLIER)
    record_tool_call_started(
        worker,
        session_id=SESSION_ID,
        tool_use_id="call-2",
        tool_name="Bash",
        started_at=LATER,
    )
    record_tool_call_finished(
        worker,
        session_id=SESSION_ID,
        tool_use_id="call-2",
        tool_name="Bash",
        event_name="HarnessToolCallCompleted",
        outcome="completed",
        completed_at=LATER,
    )
    worker.commit()

    activity = _activity(worker)
    assert activity["first_completed_work_at"] == EARLIER
    assert activity["last_completed_work_at"] == LATER


def test_a_failed_call_is_activity_but_is_not_completed_work(worker):
    """Running a wrong command is not the same as getting something done."""
    record_tool_call_started(
        worker,
        session_id=SESSION_ID,
        tool_use_id=CALL_ID,
        tool_name="Bash",
        started_at=EARLIER,
    )
    record_tool_call_finished(
        worker,
        session_id=SESSION_ID,
        tool_use_id=CALL_ID,
        tool_name="Bash",
        event_name="HarnessToolCallFailed",
        outcome="failed",
        completed_at=LATER,
    )
    worker.commit()

    activity = _activity(worker)
    assert activity["tool_call_count"] == 1
    assert activity["first_completed_work_at"] is None


def test_a_denied_call_closes_its_row_and_counts_as_no_activity(worker):
    """A refusal finishes the call without the session having acted."""
    record_tool_call_started(
        worker,
        session_id=SESSION_ID,
        tool_use_id=CALL_ID,
        tool_name="Bash",
        started_at=EARLIER,
    )
    record_tool_call_finished(
        worker,
        session_id=SESSION_ID,
        tool_use_id=CALL_ID,
        tool_name="Bash",
        event_name="HarnessToolCallDenied",
        outcome="denied",
        completed_at=LATER,
        bump_activity=False,
    )
    worker.commit()

    closed = worker.execute(
        "SELECT completed_at, outcome FROM session_tool_calls "
        "WHERE session_id = %s AND tool_use_id = %s",
        (SESSION_ID, CALL_ID),
    ).fetchone()
    assert closed["completed_at"] == LATER
    assert closed["outcome"] == "denied"
    assert _activity(worker)["tool_call_count"] == 0


def test_the_hold_ledger_exists_for_the_stop_gate(worker):
    """The ceiling needs somewhere to live that outlives telemetry."""
    worker.execute(
        f"INSERT INTO {PROMISED_WORK_HOLDS_TABLE} "
        "(session_id, item_id, hold_count, last_hold_at) VALUES (%s, 1, 1, %s)",
        (SESSION_ID, LATER),
    )
    worker.commit()

    row = worker.execute(
        f"SELECT hold_count FROM {PROMISED_WORK_HOLDS_TABLE} "
        "WHERE session_id = %s AND item_id = 1",
        (SESSION_ID,),
    ).fetchone()
    assert row["hold_count"] == 1
