"""What the relay decides about a turn the model provider ended.

Every case here is one the observed incident produced. Five workers'
turns died on an upstream 404 in eleven minutes; the seat hand-wrote five
resumes twenty minutes later, and two of those resumes died seconds after
injection on the same failure. So the questions the state reader has to
answer are: is this worth retrying at all, is it time yet, has it been
tried enough, and is the session actually idle right now.
"""

from __future__ import annotations

from datetime import timedelta

from runtime.api.domain.session_vendor_error_test_support import (
    MACHINE_ID,
    PROJECT_ID,
    SESSION_ID,
    TURN_ENDED_AT,
    observe_turn_end,
    one_state,
    record_resume,
    stamp,
    states,
    worker_connection,
)
from yoke_core.domain.session_vendor_error_states import (
    RESUME_BACKOFF_SECONDS,
    vendor_error_states,
)


def test_a_healthy_session_is_not_a_finding():
    conn = worker_connection()
    assert states(conn, now=TURN_ENDED_AT + timedelta(minutes=30)) == []


def test_the_first_attempt_waits_out_its_backoff_before_it_is_due():
    conn = worker_connection()
    observe_turn_end(conn)

    early = one_state(conn, now=TURN_ENDED_AT + timedelta(seconds=30))
    assert early["status"] == "waiting_backoff"
    assert early["signature_id"] == "client_refused"
    assert early["attempts"] == 0
    assert early["due_at"] == stamp(
        TURN_ENDED_AT + timedelta(seconds=RESUME_BACKOFF_SECONDS[0])
    )

    due = one_state(conn, now=TURN_ENDED_AT + timedelta(seconds=90))
    assert due["status"] == "due"


def test_each_attempt_waits_longer_than_the_one_before():
    """Three attempts, and each one's wait is the next backoff entry."""
    conn = worker_connection()
    observe_turn_end(conn)
    died_at = TURN_ENDED_AT
    for index, delay in enumerate(RESUME_BACKOFF_SECONDS):
        due_at = died_at + timedelta(seconds=delay)
        assert one_state(conn, now=due_at - timedelta(seconds=1))["status"] == (
            "waiting_backoff"
        ), index
        state = one_state(conn, now=due_at)
        assert state["status"] == "due", (index, state)
        assert state["attempts"] == index
        record_resume(conn, at=due_at, event_id=f"resume-{index}")
        # The provider refuses the resumed turn too, so the record is read
        # again — and no tool call ran in between, which is what keeps
        # every one of these attempts on the same budget.
        died_at = due_at
        observe_turn_end(conn, at=died_at, event_id=f"observed-retry-{index}")

    spent = one_state(conn, now=died_at + timedelta(hours=1))
    assert spent["status"] == "budget_spent"


def test_a_spent_budget_stops_resuming_and_stays_on_the_report():
    conn = worker_connection()
    observe_turn_end(conn)
    for index in range(len(RESUME_BACKOFF_SECONDS)):
        record_resume(
            conn,
            at=TURN_ENDED_AT + timedelta(seconds=index + 1),
            event_id=f"resume-{index}",
        )

    spent = one_state(conn, now=TURN_ENDED_AT + timedelta(hours=2))
    assert spent["status"] == "budget_spent"
    assert spent["attempts"] == len(RESUME_BACKOFF_SECONDS)
    assert spent["budget"] == len(RESUME_BACKOFF_SECONDS)


def test_a_resume_that_produced_real_work_starts_the_budget_over():
    """Work done between failures is progress, not the same stuck session."""
    conn = worker_connection()
    observe_turn_end(conn)
    record_resume(
        conn, at=TURN_ENDED_AT + timedelta(seconds=61), event_id="resume-0"
    )
    worked_at = TURN_ENDED_AT + timedelta(minutes=5)
    conn.execute(
        "UPDATE harness_sessions SET last_tool_call_at=? WHERE session_id=?",
        (stamp(worked_at), SESSION_ID),
    )
    conn.commit()
    # Nothing is owed while the last thing this session did was work.
    assert states(conn, now=worked_at + timedelta(minutes=1)) == []

    died_again = worked_at + timedelta(minutes=2)
    observe_turn_end(conn, at=died_again, event_id="observed-2")

    fresh = one_state(conn, now=died_again + timedelta(seconds=90))
    assert fresh["status"] == "due"
    assert fresh["attempts"] == 0


def test_a_failure_no_attempt_can_move_names_the_seat_immediately():
    conn = worker_connection()
    observe_turn_end(
        conn,
        error_message="You have hit your usage limit for this window",
        vendor_code="usage_limit_reached",
    )

    state = one_state(conn, now=TURN_ENDED_AT + timedelta(minutes=30))
    assert state["status"] == "seat_required"
    assert state["signature_id"] == "quota_exhausted"
    assert state["budget"] == 0


def test_a_session_inside_an_unreturned_tool_call_is_never_resumed():
    conn = worker_connection()
    observe_turn_end(conn)
    conn.execute(
        "INSERT INTO session_tool_calls "
        "(session_id,tool_use_id,tool_name,started_at,completed_at) "
        "VALUES (?,'call-1','Bash',?,NULL)",
        (SESSION_ID, stamp(TURN_ENDED_AT + timedelta(minutes=1))),
    )
    conn.commit()

    state = one_state(conn, now=TURN_ENDED_AT + timedelta(minutes=30))
    assert state["status"] == "turn_in_flight"
    assert state["in_flight_since"] == stamp(TURN_ENDED_AT + timedelta(minutes=1))


def test_a_completed_tool_call_does_not_block_the_resume():
    conn = worker_connection()
    observe_turn_end(conn)
    conn.execute(
        "INSERT INTO session_tool_calls "
        "(session_id,tool_use_id,tool_name,started_at,completed_at) "
        "VALUES (?,'call-1','Bash',?,?)",
        (
            SESSION_ID,
            stamp(TURN_ENDED_AT - timedelta(minutes=5)),
            stamp(TURN_ENDED_AT - timedelta(minutes=4)),
        ),
    )
    conn.commit()

    ready = one_state(conn, now=TURN_ENDED_AT + timedelta(minutes=30))
    assert ready["status"] == "due"


def test_states_are_scoped_to_the_asking_machine_and_its_projects():
    conn = worker_connection()
    observe_turn_end(conn)
    now = TURN_ENDED_AT + timedelta(minutes=30)
    assert (
        vendor_error_states(
            conn,
            machine_id="machine-9",
            authorized_projects=(PROJECT_ID,),
            now=now,
        )
        == []
    )
    assert (
        vendor_error_states(
            conn, machine_id=MACHINE_ID, authorized_projects=(999,), now=now
        )
        == []
    )
