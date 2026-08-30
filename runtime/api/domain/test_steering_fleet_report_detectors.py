"""The five failures that arrive as silence, and the guesses not made about them."""

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
from yoke_core.domain.steering_fleet_report_dead_waits import UNRESOLVED, dead_waits
from yoke_core.domain.steering_fleet_report_detectors import (
    landed_without_closeout,
    starved_deliveries,
    suspected_orphaned_waiters,
    unregistered_launches,
)


def _send(conn, message_id: str, *, sender: str, to: str, at: str, state="pending"):
    conn.execute(
        "INSERT INTO session_messages "
        "(message_id, sender_actor_id, sender_session_id, body, body_sha256, "
        "selector_snapshot, created_at, expires_at) "
        "VALUES (%s, %s, %s, 'a question', 'sha', %s, %s, %s)",
        (message_id, ACTOR_ID, sender, json.dumps({}), at, NOW),
    )
    conn.execute(
        "INSERT INTO session_message_recipients "
        "(message_id, session_id, project_id, resolution_evidence, "
        "routing_snapshot, state, created_at, wake_after, injection_count) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 0)",
        (message_id, to, PROJECT_ID, json.dumps({}), json.dumps({}), state, at, at),
    )


def _launch(
    conn,
    launch_id: str,
    *,
    deadline: str,
    state="awaiting_registration",
    result_code=None,
    native_session_id=None,
):
    conn.execute(
        "INSERT INTO session_messages "
        "(message_id, sender_actor_id, sender_session_id, body, body_sha256, "
        "selector_snapshot, created_at, expires_at) "
        "VALUES (%s, %s, %s, 'launch instruction', 'sha', %s, %s, %s)",
        (f"msg-{launch_id}", ACTOR_ID, ASKER, json.dumps({}), LONG_AGO, NOW),
    )
    conn.execute(
        "INSERT INTO session_launches "
        "(launch_id, requester_actor_id, project_id, requested_surface, "
        "selected_surface, allow_surface_fallback, message_id, state, "
        "deadline_at, created_at, origin, assigned_machine_id, result_code, "
        "native_session_id) "
        "VALUES (%s, %s, %s, 'codex-cli', 'codex-cli', 0, %s, %s, %s, %s, "
        "'operator', 'machine-1', %s, %s)",
        (
            launch_id,
            ACTOR_ID,
            PROJECT_ID,
            f"msg-{launch_id}",
            state,
            deadline,
            LONG_AGO,
            result_code,
            native_session_id,
        ),
    )


def _complete_tool(conn, session_id: str, tool_name: str) -> None:
    conn.execute(
        "INSERT INTO events "
        "(event_id, source_type, session_id, event_kind, event_type, event_name, "
        "tool_name, created_at) VALUES (%s, 'hook', %s, 'system', 'tool_call', "
        "'HarnessToolCallCompleted', %s, %s)",
        (f"event-{session_id}-{tool_name}", session_id, tool_name, LONG_AGO),
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


def test_an_envelope_never_injected_to_a_silent_recipient_is_starved(fleet):
    _send(fleet, "msg-1", sender=ASKER, to=ANSWERER, at=LONG_AGO)
    fleet.commit()

    starved = starved_deliveries(fleet, project_id=PROJECT_ID, now=NOW)

    assert [entry.session_id for entry in starved] == [ANSWERER]
    assert starved[0].envelope_count == 1


def test_a_worker_to_worker_envelope_starves_like_any_other(fleet):
    """Sender is not a filter: the steerer did not have to send it to matter."""
    _send(fleet, "msg-1", sender=ASKER, to=ANSWERER, at=LONG_AGO)
    _send(fleet, "msg-2", sender=ANSWERER, to=ASKER, at=LONG_AGO)
    fleet.commit()

    starved = starved_deliveries(fleet, project_id=PROJECT_ID, now=NOW)

    assert {entry.session_id for entry in starved} == {ASKER, ANSWERER}


def test_a_recipient_that_has_run_a_tool_since_the_send_is_not_starved(fleet):
    _send(fleet, "msg-1", sender=ASKER, to=ANSWERER, at=LONG_AGO)
    fleet.execute(
        "UPDATE harness_sessions SET last_tool_call_at = %s WHERE session_id = %s",
        (JUST_NOW, ANSWERER),
    )
    fleet.commit()

    assert starved_deliveries(fleet, project_id=PROJECT_ID, now=NOW) == ()


def test_an_envelope_inside_the_grace_window_is_not_yet_starved(fleet):
    _send(fleet, "msg-1", sender=ASKER, to=ANSWERER, at=JUST_NOW)
    fleet.commit()

    assert starved_deliveries(fleet, project_id=PROJECT_ID, now=NOW) == ()


def test_an_ended_recipient_is_not_a_starved_worker(fleet):
    _send(fleet, "msg-1", sender=ASKER, to=ANSWERER, at=LONG_AGO)
    fleet.execute(
        "UPDATE harness_sessions SET ended_at = %s WHERE session_id = %s",
        (JUST_NOW, ANSWERER),
    )
    fleet.commit()

    assert starved_deliveries(fleet, project_id=PROJECT_ID, now=NOW) == ()


@pytest.mark.parametrize(
    ("turn_posture", "tool_name", "past_idle_threshold", "expected"),
    [
        ("waiting", "Monitor", True, True),
        ("running", "Monitor", True, False),
        ("waiting", "Bash", True, False),
        ("waiting", "Monitor", False, False),
    ],
)
def test_only_the_full_monitor_freeze_signature_is_suspected(
    fleet, turn_posture, tool_name, past_idle_threshold, expected
):
    fleet.execute(
        "UPDATE harness_sessions SET turn_posture = %s WHERE session_id = %s",
        (turn_posture, ASKER),
    )
    _complete_tool(fleet, ASKER, tool_name)
    fleet.commit()

    idle = [quiet_holder(ASKER)] if past_idle_threshold else []
    matches = suspected_orphaned_waiters(fleet, idle=idle)

    assert bool(matches) is expected
    if matches:
        assert matches[0].session_id == ASKER
        assert matches[0].public_ref == "YOK-1"


def test_a_launch_past_its_deadline_with_no_session_is_reported(fleet):
    _launch(fleet, "launch-1", deadline=LONG_AGO)
    fleet.commit()

    overdue = unregistered_launches(fleet, project_id=PROJECT_ID, now=NOW)

    assert [entry.launch_id for entry in overdue] == ["launch-1"]
    assert overdue[0].surface == "codex-cli"
    assert overdue[0].overdue_seconds == 3 * 3600


def test_identity_parse_failure_is_reported_before_the_deadline(fleet):
    _launch(
        fleet,
        "launch-parse-failed",
        deadline="2026-08-26T12:10:00Z",
        state="outcome_unknown",
        result_code="identity_parse_failed",
    )
    fleet.commit()

    gaps = unregistered_launches(fleet, project_id=PROJECT_ID, now=NOW)

    assert [entry.launch_id for entry in gaps] == ["launch-parse-failed"]
    assert gaps[0].overdue_seconds == 0
    assert gaps[0].result_code == "identity_parse_failed"


def test_exact_registered_session_with_missing_launch_binding_is_named(fleet):
    _launch(
        fleet,
        "launch-existing-session",
        deadline="2026-08-26T12:10:00Z",
        state="outcome_unknown",
        result_code="late_native_requires_reconciliation",
        native_session_id=ANSWERER,
    )
    fleet.commit()

    gaps = unregistered_launches(fleet, project_id=PROJECT_ID, now=NOW)

    assert [entry.launch_id for entry in gaps] == ["launch-existing-session"]
    assert gaps[0].observed_session_id == ANSWERER
    assert gaps[0].overdue_seconds == 0


def test_a_launch_that_registered_a_session_is_not_reported(fleet):
    _launch(fleet, "launch-1", deadline=LONG_AGO)
    fleet.execute(
        "UPDATE session_launches SET registered_session_id = %s WHERE launch_id = %s",
        (ANSWERER, "launch-1"),
    )
    fleet.commit()

    assert unregistered_launches(fleet, project_id=PROJECT_ID, now=NOW) == ()


def test_a_launch_the_deadline_sweep_already_closed_is_not_reported(fleet):
    """A closed launch needs no reconcile; including them grows without bound."""
    _launch(fleet, "launch-1", deadline=LONG_AGO, state="expired")
    fleet.commit()

    assert unregistered_launches(fleet, project_id=PROJECT_ID, now=NOW) == ()


def test_a_merged_branch_on_an_open_item_is_reported(fleet):
    fleet.execute("UPDATE items SET merged_at = %s WHERE id = 1", (LONG_AGO,))
    fleet.commit()

    landed = landed_without_closeout(fleet, project_id=PROJECT_ID, now=NOW)

    assert [entry.item_id for entry in landed] == [1]
    assert landed[0].status == "implementing"
    assert landed[0].landed_seconds == 3 * 3600


def test_a_merged_branch_on_a_closed_item_is_not_reported(fleet):
    fleet.execute(
        "UPDATE items SET merged_at = %s, status = 'done' WHERE id = 1",
        (LONG_AGO,),
    )
    fleet.commit()

    assert landed_without_closeout(fleet, project_id=PROJECT_ID, now=NOW) == ()


def test_a_queue_landing_counts_as_the_branch_landing(fleet):
    fleet.execute(
        "UPDATE items SET merge_queue_landed_at = %s WHERE id = 1",
        (LONG_AGO,),
    )
    fleet.commit()

    landed = landed_without_closeout(fleet, project_id=PROJECT_ID, now=NOW)

    assert [entry.item_id for entry in landed] == [1]


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
