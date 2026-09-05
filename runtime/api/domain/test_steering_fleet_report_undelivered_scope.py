"""Which unread envelopes reach the section, and how they are grouped.

Membership is where this section was wrong rather than merely unhelpful. A
live-recipient filter hid the one loss no later poll can resolve, and a
receipt whose ``state`` column had not caught up to its own expiry read as
a worker still waiting. Which state each included envelope lands in is
covered by ``test_steering_fleet_report_undelivered``.
"""

from __future__ import annotations

import pytest

from runtime.api.steering_fleet_test_helpers import (
    ANSWERER,
    ASKER,
    BEFORE_THAT,
    JUST_NOW,
    LONG_AGO,
    NOW,
    PROJECT_ID,
    seed_delivery_attempt,
    seed_message,
    seed_session,
)
from yoke_core.domain.steering_fleet_report_delivery_states import (
    ATTEMPT_FAILED,
    ATTEMPT_IN_FLIGHT,
    AWAITING_ATTEMPT,
    NEVER_ATTEMPTED,
    RECIPIENT_ENDED,
    RECIPIENT_TERMINATED,
)
from yoke_core.domain.steering_fleet_report_undelivered import undelivered_messages


@pytest.fixture
def fleet(test_db):
    """Two ordinary workers, quiet since before any message was sent."""
    seed_session(test_db, ASKER, last_tool_call_at=BEFORE_THAT)
    seed_session(test_db, ANSWERER, last_tool_call_at=BEFORE_THAT)
    test_db.commit()
    return test_db


def _states(conn) -> dict[str, str]:
    """Each recipient's delivery state, for the one-row-per-session cases."""
    return {
        entry.session_id: entry.delivery_state
        for entry in undelivered_messages(conn, project_id=PROJECT_ID, now=NOW)
    }


def test_a_worker_to_worker_envelope_is_reported_like_any_other(fleet):
    """Sender is not a filter: the steerer did not have to send it to matter."""
    seed_message(fleet, "msg-1", sender=ASKER, to=ANSWERER, at=LONG_AGO)
    seed_message(fleet, "msg-2", sender=ANSWERER, to=ASKER, at=LONG_AGO)
    fleet.commit()

    assert set(_states(fleet)) == {ASKER, ANSWERER}


def test_every_row_names_the_envelopes_behind_it(fleet):
    """A count alone cannot be looked up; the seat needs the references."""
    seed_message(fleet, "msg-1", sender=ASKER, to=ANSWERER, at=LONG_AGO)
    seed_message(fleet, "msg-2", sender=ASKER, to=ANSWERER, at=LONG_AGO)
    fleet.commit()

    rows = undelivered_messages(fleet, project_id=PROJECT_ID, now=NOW)

    assert rows[0].envelope_count == 2
    assert set(rows[0].message_ids) == {"msg-1", "msg-2"}


def test_an_ended_recipient_is_reported_as_a_lost_delivery(fleet):
    """The live-recipient filter hid the one loss no poll will ever resolve.

    An envelope addressed to a session that wound down is not a worker
    waiting on a message, but it is also not delivered, and the seat that
    sent it has no other way to learn that it never arrived.
    """
    seed_message(fleet, "msg-1", sender=ASKER, to=ANSWERER, at=LONG_AGO)
    fleet.execute(
        "UPDATE harness_sessions SET ended_at = %s WHERE session_id = %s",
        (JUST_NOW, ANSWERER),
    )
    fleet.commit()

    rows = undelivered_messages(fleet, project_id=PROJECT_ID, now=NOW)

    assert [entry.session_id for entry in rows] == [ANSWERER]
    assert rows[0].delivery_state == RECIPIENT_ENDED
    assert rows[0].recipient_gone_at == JUST_NOW
    # Nothing to revive, so this is a fact to read rather than the seat's work.
    assert rows[0].needs_seat_action is False


def test_a_terminated_recipient_is_named_apart_from_one_that_wound_down(fleet):
    """Both are gone; only one was gone on purpose."""
    seed_message(fleet, "msg-1", sender=ASKER, to=ANSWERER, at=LONG_AGO)
    fleet.execute(
        "UPDATE harness_sessions SET terminated_at = %s WHERE session_id = %s",
        (JUST_NOW, ANSWERER),
    )
    fleet.commit()

    assert _states(fleet) == {ANSWERER: RECIPIENT_TERMINATED}


def test_an_injected_envelope_has_left_the_undelivered_view(fleet):
    """Delivered is delivered, acknowledged or not."""
    seed_message(
        fleet, "msg-1", sender=ASKER, to=ANSWERER, at=LONG_AGO, state="injected"
    )
    fleet.commit()

    assert undelivered_messages(fleet, project_id=PROJECT_ID, now=NOW) == ()


def test_an_acknowledged_envelope_has_left_the_undelivered_view(fleet):
    seed_message(
        fleet, "msg-1", sender=ASKER, to=ANSWERER, at=LONG_AGO, state="acknowledged"
    )
    fleet.commit()

    assert undelivered_messages(fleet, project_id=PROJECT_ID, now=NOW) == ()


def test_an_expired_envelope_is_gone_before_the_sweep_converges_its_row(fleet):
    """Expiry is swept, so the row reads `pending` for a while after the fact.

    Reading the deadline directly is what keeps a finished envelope from
    reading as a worker still waiting during that window.
    """
    seed_message(
        fleet,
        "msg-1",
        sender=ASKER,
        to=ANSWERER,
        at=LONG_AGO,
        expires_at=JUST_NOW,
    )
    fleet.commit()

    assert undelivered_messages(fleet, project_id=PROJECT_ID, now=NOW) == ()


def test_a_cancelled_message_is_gone_before_the_sweep_converges_its_row(fleet):
    seed_message(
        fleet,
        "msg-1",
        sender=ASKER,
        to=ANSWERER,
        at=LONG_AGO,
        cancelled_at=JUST_NOW,
    )
    fleet.commit()

    assert undelivered_messages(fleet, project_id=PROJECT_ID, now=NOW) == ()


def test_one_recipients_two_situations_get_a_row_each(fleet):
    """A count and a reason that disagree are worse than two lines.

    Grouping stays per recipient because the action is, but a failed
    attempt and a queued one are different situations, and folding them
    into one row would label the queued envelope with the failure.
    """
    seed_message(fleet, "msg-failed", sender=ASKER, to=ANSWERER, at=LONG_AGO)
    seed_delivery_attempt(
        fleet,
        "attempt-1",
        message_id="msg-failed",
        to=ANSWERER,
        result_code="failed",
        evidence={"result_code": "instruction_invalid"},
        started_at=LONG_AGO,
    )
    seed_message(fleet, "msg-queued", sender=ASKER, to=ANSWERER, at=NOW)
    seed_delivery_attempt(
        fleet,
        "attempt-2",
        message_id="msg-queued",
        to=ANSWERER,
        result_code="accepted",
        started_at=NOW,
    )
    fleet.commit()

    rows = undelivered_messages(fleet, project_id=PROJECT_ID, now=NOW)

    assert [entry.delivery_state for entry in rows] == [
        ATTEMPT_FAILED,
        ATTEMPT_IN_FLIGHT,
    ]
    assert [entry.message_ids for entry in rows] == [("msg-failed",), ("msg-queued",)]
    assert [entry.envelope_count for entry in rows] == [1, 1]


def test_the_states_the_seat_owes_sort_ahead_of_the_ones_it_does_not(fleet):
    """The section is capped, so a waiting row must never crowd out a finding."""
    seed_session(fleet, "gone-worker", last_tool_call_at=BEFORE_THAT, ended_at=JUST_NOW)
    seed_message(fleet, "msg-waiting", sender=ASKER, to=ANSWERER, at=NOW)
    seed_message(fleet, "msg-gone", sender=ASKER, to="gone-worker", at=LONG_AGO)
    seed_message(fleet, "msg-owed", sender=ANSWERER, to=ASKER, at=LONG_AGO)
    fleet.commit()

    rows = undelivered_messages(fleet, project_id=PROJECT_ID, now=NOW)

    assert [entry.delivery_state for entry in rows] == [
        NEVER_ATTEMPTED,
        RECIPIENT_ENDED,
        AWAITING_ATTEMPT,
    ]
