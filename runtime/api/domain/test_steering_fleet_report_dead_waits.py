"""Whether the answer an idle holder waits on can still arrive.

The one negative-space check that asks about the future rather than about
elapsed time, so both wrong answers cost real work: a false positive sends
the seat to answer a question nobody asked, a false negative leaves a
worker parked on a reply that is never coming.
"""

from __future__ import annotations

import json

import pytest

from runtime.api.fixtures.backlog import insert_item
from runtime.api.steering_fleet_test_helpers import (
    ACTOR_ID,
    ANSWERER,
    ASKER,
    BEFORE_THAT,
    JUST_NOW,
    LONG_AGO,
    NOW,
    PROJECT_ID,
    quiet_holder,
    seed_session,
)
from yoke_core.domain.steering_fleet_report_dead_waits import (
    UNRESOLVED,
    dead_waits,
    message_asks,
)


#: A message that wants something back, so waiting on it is a real wait.
A_QUESTION = "Did the rebase land clean, or do you need the base moved?"
#: A message that closes a topic. Its sender is not waiting on anything.
A_CONFIRMATION = "Confirmed, YOK-1 is merged. No reply needed."


def _send(
    conn,
    message_id: str,
    *,
    sender,
    to,
    at,
    state="pending",
    body=A_QUESTION,
) -> None:
    conn.execute(
        "INSERT INTO session_messages "
        "(message_id, sender_actor_id, sender_session_id, body, body_sha256, "
        "selector_snapshot, created_at, expires_at) "
        "VALUES (%s, %s, %s, %s, 'sha', %s, %s, %s)",
        (message_id, ACTOR_ID, sender, body, json.dumps({}), at, NOW),
    )
    conn.execute(
        "INSERT INTO session_message_recipients "
        "(message_id, session_id, project_id, resolution_evidence, "
        "routing_snapshot, state, created_at, wake_after, injection_count) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 0)",
        (message_id, to, PROJECT_ID, json.dumps({}), json.dumps({}), state, at, at),
    )


@pytest.fixture
def fleet(test_db):
    """Two ordinary workers and one item, before any failure is introduced."""
    seed_session(test_db, ASKER, last_tool_call_at=BEFORE_THAT)
    seed_session(test_db, ANSWERER, last_tool_call_at=BEFORE_THAT)
    insert_item(
        test_db,
        id=1,
        title="Some work",
        status="implementing",
        created_at=LONG_AGO,
        updated_at=LONG_AGO,
    )
    test_db.commit()
    return test_db


def test_a_question_to_an_ended_session_is_a_dead_wait(fleet):
    _send(fleet, "msg-1", sender=ASKER, to=ANSWERER, at=LONG_AGO)
    fleet.execute(
        "UPDATE harness_sessions SET ended_at = %s WHERE session_id = %s",
        (JUST_NOW, ANSWERER),
    )
    fleet.commit()

    waits = dead_waits(fleet, idle=[quiet_holder(ASKER)], now=NOW)

    assert [entry.session_id for entry in waits] == [ASKER]
    assert waits[0].reason == "answerer session has ended"
    assert waits[0].answer_impossible is True


def test_a_question_to_a_worker_whose_item_is_done_is_a_dead_wait(fleet):
    _send(fleet, "msg-1", sender=ASKER, to=ANSWERER, at=LONG_AGO)
    fleet.execute("UPDATE items SET status = 'done' WHERE id = 1")
    fleet.execute(
        "UPDATE harness_sessions SET current_item_id = 1 WHERE session_id = %s",
        (ANSWERER,),
    )
    fleet.commit()

    waits = dead_waits(fleet, idle=[quiet_holder(ASKER)], now=NOW)

    assert waits[0].reason == "answerer's own item is already terminal"


def test_a_live_answerer_leaves_the_wait_unresolved_rather_than_dead(fleet):
    """A false positive sends the steerer to answer a question nobody asked."""
    _send(fleet, "msg-1", sender=ASKER, to=ANSWERER, at=LONG_AGO)
    fleet.commit()

    waits = dead_waits(fleet, idle=[quiet_holder(ASKER)], now=NOW)

    assert waits[0].reason == UNRESOLVED
    assert waits[0].answer_impossible is False


def test_an_answer_that_already_came_back_is_not_a_dead_wait(fleet):
    """The answerer replied and then ended; the asker already has its answer."""
    _send(fleet, "msg-1", sender=ASKER, to=ANSWERER, at=LONG_AGO)
    _send(fleet, "msg-2", sender=ANSWERER, to=ASKER, at=JUST_NOW, state="acknowledged")
    fleet.execute(
        "UPDATE harness_sessions SET ended_at = %s WHERE session_id = %s",
        (NOW, ANSWERER),
    )
    fleet.commit()

    assert dead_waits(fleet, idle=[quiet_holder(ASKER)], now=NOW) == ()


def test_an_idle_holder_that_asked_nobody_produces_no_row(fleet):
    """Its silence has some other cause; inventing a wait is the other guess."""
    assert dead_waits(fleet, idle=[quiet_holder(ASKER)], now=NOW) == ()


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (A_QUESTION, True),
        ("Which lane holds the claim?", True),
        ("Please reply with the run id once it lands.", True),
        ("Let me know whether the gate went green.", True),
        ("Confirm whether the gate went green before I push.", True),
        (A_CONFIRMATION, False),
        ("Merged and deployed. No reply needed.", False),
        ("Seat note: field-note 44959 has the detail.", False),
        ("", False),
        (None, False),
    ],
)
def test_only_a_message_that_wants_something_back_counts_as_asking(body, expected):
    assert message_asks(body) is expected


def test_a_confirmation_to_an_ended_session_is_not_a_dead_wait(fleet):
    """Nobody is waiting, so the ended answerer costs the sender nothing."""
    _send(fleet, "msg-1", sender=ASKER, to=ANSWERER, at=LONG_AGO, body=A_CONFIRMATION)
    fleet.execute(
        "UPDATE harness_sessions SET ended_at = %s WHERE session_id = %s",
        (JUST_NOW, ANSWERER),
    )
    fleet.commit()

    assert dead_waits(fleet, idle=[quiet_holder(ASKER)], now=NOW) == ()


def test_a_confirmation_sent_after_a_question_does_not_hide_the_real_wait(fleet):
    """The newest message is not always the one its sender is waiting on."""
    _send(fleet, "msg-1", sender=ASKER, to=ANSWERER, at=LONG_AGO)
    _send(fleet, "msg-2", sender=ASKER, to=ANSWERER, at=JUST_NOW, body=A_CONFIRMATION)
    fleet.execute(
        "UPDATE harness_sessions SET ended_at = %s WHERE session_id = %s",
        (NOW, ANSWERER),
    )
    fleet.commit()

    waits = dead_waits(fleet, idle=[quiet_holder(ASKER)], now=NOW)

    assert [entry.session_id for entry in waits] == [ASKER]
    assert waits[0].reason == "answerer session has ended"


def test_a_role_addressed_question_is_a_handoff_rather_than_a_dead_wait(fleet):
    """The next seat drains it, so an ended answerer is not a dead end."""
    _send(fleet, "msg-1", sender=ASKER, to=ANSWERER, at=LONG_AGO)
    fleet.execute(
        "INSERT INTO actor_message_recipients "
        "(message_id, recipient_kind, state, steering_scope, project_id, "
        "created_at) VALUES ('msg-1', 'steering', 'awaiting_seat', %s, %s, %s)",
        (json.dumps({"project_id": PROJECT_ID}), PROJECT_ID, LONG_AGO),
    )
    fleet.execute(
        "UPDATE harness_sessions SET ended_at = %s WHERE session_id = %s",
        (JUST_NOW, ANSWERER),
    )
    fleet.commit()

    assert dead_waits(fleet, idle=[quiet_holder(ASKER)], now=NOW) == ()
