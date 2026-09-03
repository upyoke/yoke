"""What the seat is told about an envelope nobody delivered."""

from __future__ import annotations

import json

import pytest

from runtime.api.steering_fleet_test_helpers import (
    ACTOR_ID,
    ANSWERER,
    ASKER,
    BEFORE_THAT,
    JUST_NOW,
    LONG_AGO,
    NOW,
    PROJECT_ID,
    seed_session,
)
from yoke_core.domain.steering_fleet_report_starvation import starved_deliveries


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


def _attempt(
    conn,
    attempt_id: str,
    *,
    message_id: str,
    to: str,
    result_code: str,
    evidence: dict | None = None,
    started_at: str = JUST_NOW,
    kind: str = "wake_relay",
):
    conn.execute(
        "INSERT INTO session_message_attempts "
        "(attempt_id, message_id, target_session_id, attempt_kind, started_at, "
        "completed_at, result_code, evidence) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (
            attempt_id,
            message_id,
            to,
            kind,
            started_at,
            started_at,
            result_code,
            json.dumps(evidence or {}),
        ),
    )


@pytest.fixture
def fleet(test_db):
    """Two ordinary workers, quiet since before any message was sent."""
    seed_session(test_db, ASKER, last_tool_call_at=BEFORE_THAT)
    seed_session(test_db, ANSWERER, last_tool_call_at=BEFORE_THAT)
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


def test_a_zero_attempt_envelope_is_starved_on_the_recipients_own_silence(fleet):
    """The silence that matters started before the message did.

    A worker quiet for four hours is not going to run the hook that would
    attach an envelope sent two minutes ago, and the plane owes it a wake
    right away. Counting the wait from the send instead bought that envelope
    another grace window of quiet, and four steering waits were abandoned by
    hand inside exactly that window in one night.
    """
    _send(fleet, "msg-1", sender=ASKER, to=ANSWERER, at=JUST_NOW)
    fleet.commit()

    starved = starved_deliveries(fleet, project_id=PROJECT_ID, now=NOW)

    assert [entry.session_id for entry in starved] == [ANSWERER]
    assert starved[0].attempt_count == 0
    assert starved[0].diagnostic == ""


def test_an_envelope_still_inside_the_delivery_sla_is_not_yet_starved(fleet):
    """One relay poll to actually make the attempt is not a failure."""
    _send(fleet, "msg-1", sender=ASKER, to=ANSWERER, at=NOW)
    fleet.commit()

    assert starved_deliveries(fleet, project_id=PROJECT_ID, now=NOW) == ()


def test_a_failed_attempt_is_reported_with_its_named_diagnostic(fleet):
    """`failed` alone cannot be acted on; the reason behind it can."""
    _send(fleet, "msg-1", sender=ASKER, to=ANSWERER, at=NOW)
    _attempt(
        fleet,
        "attempt-1",
        message_id="msg-1",
        to=ANSWERER,
        result_code="failed",
        evidence={"result_code": "instruction_invalid"},
        started_at=NOW,
    )
    fleet.commit()

    starved = starved_deliveries(fleet, project_id=PROJECT_ID, now=NOW)

    assert [entry.session_id for entry in starved] == [ANSWERER]
    assert starved[0].diagnostic == "instruction_invalid"
    assert starved[0].attempt_count == 1


def test_a_failed_attempt_with_no_reason_still_says_so(fleet):
    _send(fleet, "msg-1", sender=ASKER, to=ANSWERER, at=NOW)
    _attempt(fleet, "attempt-1", message_id="msg-1", to=ANSWERER, result_code="failed")
    fleet.commit()

    starved = starved_deliveries(fleet, project_id=PROJECT_ID, now=NOW)

    assert starved[0].diagnostic == "unreported"


def test_an_attempt_still_in_flight_is_not_a_starved_delivery(fleet):
    """An accepted resume may still deliver; only a settled failure is one."""
    _send(fleet, "msg-1", sender=ASKER, to=ANSWERER, at=LONG_AGO)
    _attempt(
        fleet,
        "attempt-1",
        message_id="msg-1",
        to=ANSWERER,
        result_code="accepted",
        started_at=LONG_AGO,
    )
    fleet.commit()

    assert starved_deliveries(fleet, project_id=PROJECT_ID, now=NOW) == ()


def test_a_desktop_recipient_is_flagged_as_its_operators_to_wake(fleet):
    """The seat cannot revive this one, so the row must say so.

    Everything else about the finding is identical — pending, never
    injected, silent past the window — and the action is completely
    different, because Yoke never resumes an operator-opened chat.
    """
    fleet.execute(
        "UPDATE harness_sessions SET executor_surface = %s WHERE session_id = %s",
        ("claude-desktop", ANSWERER),
    )
    _send(fleet, "msg-1", sender=ASKER, to=ANSWERER, at=LONG_AGO)
    _send(fleet, "msg-2", sender=ANSWERER, to=ASKER, at=LONG_AGO)
    fleet.commit()

    starved = {
        entry.session_id: entry.operator_wake
        for entry in starved_deliveries(fleet, project_id=PROJECT_ID, now=NOW)
    }

    assert starved == {ANSWERER: True, ASKER: False}


def test_an_ended_recipient_is_not_a_starved_worker(fleet):
    _send(fleet, "msg-1", sender=ASKER, to=ANSWERER, at=LONG_AGO)
    fleet.execute(
        "UPDATE harness_sessions SET ended_at = %s WHERE session_id = %s",
        (JUST_NOW, ANSWERER),
    )
    fleet.commit()

    assert starved_deliveries(fleet, project_id=PROJECT_ID, now=NOW) == ()
