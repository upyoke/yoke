"""The seat itself: one holder per overlapping scope, and its inherited mail."""

from __future__ import annotations

import json

import pytest

from runtime.api.steering_fleet_test_helpers import (
    ACTOR_ID,
    LONG_AGO,
    NOW,
    PROJECT_ID,
    STEERING_SESSION,
    WORKER_SESSION,
    compose as _compose,
    seed_session,
    seed_steering_scope,
)
from yoke_core.domain.sessions_analytics import SessionError
from yoke_core.domain.sessions_lifecycle_claim import release_claim
from yoke_core.domain.steering_claims import acquire as acquire_steering, list_claims
from yoke_core.domain.steering_fleet_report_render import report_body
from yoke_core.domain.steering_message_drain import DIGEST_BEGIN


@pytest.fixture
def steering_scope(test_db):
    return seed_steering_scope(test_db)


def _park_role_message(conn, message_id: str, *, sender: str = WORKER_SESSION) -> None:
    conn.execute(
        "INSERT INTO session_messages "
        "(message_id, sender_actor_id, sender_session_id, body, body_sha256, "
        "selector_snapshot, created_at, expires_at) "
        "VALUES (%s, %s, %s, 'Blocked: the gate went red on converge.', 'sha', "
        "%s, %s, %s)",
        (message_id, ACTOR_ID, sender, json.dumps({}), LONG_AGO, NOW),
    )
    conn.execute(
        "INSERT INTO actor_message_recipients "
        "(message_id, recipient_kind, state, steering_scope, project_id, "
        "created_at) VALUES (%s, 'steering', 'awaiting_seat', %s, %s, %s)",
        (message_id, json.dumps({"project_id": PROJECT_ID}), PROJECT_ID, LONG_AGO),
    )
    conn.commit()


def _release_the_seat(conn) -> None:
    """Release the seat the way an operator does, document lock and all."""
    held = list_claims(conn, project_id=PROJECT_ID, active_only=True)
    release_claim(conn, int(held[0]["id"]), reason="handed_off")
    conn.commit()


def test_an_overlapping_scope_is_refused_and_names_the_holder(steering_scope):
    seed_session(steering_scope, "second-steerer")
    steering_scope.commit()

    with pytest.raises(SessionError) as raised:
        acquire_steering(
            steering_scope,
            session_id="second-steerer",
            project_id=PROJECT_ID,
            reason="take the seat",
        )

    assert raised.value.code == "ALREADY_CLAIMED"
    message = str(raised.value)
    assert f"actor {ACTOR_ID}" in message
    assert STEERING_SESSION in message


def test_acquiring_the_seat_hands_over_the_scope_parked_mail(steering_scope):
    seed_session(steering_scope, "successor-seat")
    _park_role_message(steering_scope, "msg-parked")
    _release_the_seat(steering_scope)

    report = _compose(steering_scope, session_id="successor-seat")
    claim = acquire_steering(
        steering_scope,
        session_id="successor-seat",
        project_id=PROJECT_ID,
        reason="successor seat",
    )

    handoff = claim["message_handoff"]
    assert handoff["drained_count"] == report.messages_awaiting_seat
    assert handoff["drained_count"] == 1
    assert handoff["parked_count"] == 1
    assert handoff["digest"].startswith(DIGEST_BEGIN)
    assert "the gate went red on converge" in handoff["digest"]
    row = steering_scope.execute(
        "SELECT state, seat_session_id FROM actor_message_recipients "
        "WHERE message_id = 'msg-parked'"
    ).fetchone()
    assert dict(row) == {"state": "delivered", "seat_session_id": "successor-seat"}


def test_a_clean_acquire_reports_no_handoff(steering_scope):
    _release_the_seat(steering_scope)

    claim = acquire_steering(
        steering_scope,
        session_id=WORKER_SESSION,
        project_id=PROJECT_ID,
        reason="successor seat",
    )

    assert claim["message_handoff"] == {
        "drained_count": 0,
        "parked_count": 0,
        "digest": "",
    }


def test_the_report_counts_mail_no_seat_has_taken(steering_scope):
    """Work addressed to the seat is otherwise invisible while none exists."""
    _park_role_message(steering_scope, "msg-parked")

    report = _compose(steering_scope)

    assert report.messages_awaiting_seat == 1
    assert report.actionable is True
    rendered = report_body(report)
    assert "1 steering message(s) awaiting a seat" in rendered
    assert "acknowledged reports stay settled" in rendered


def test_the_report_stays_quiet_when_every_message_has_a_seat(steering_scope):
    report = _compose(steering_scope)

    assert report.messages_awaiting_seat == 0
    assert "awaiting a seat" not in report_body(report)


def test_acknowledged_mail_is_absent_from_report_and_successor_handoff(
    steering_scope,
):
    seed_session(steering_scope, "successor-seat")
    _park_role_message(steering_scope, "msg-acknowledged")
    held = list_claims(steering_scope, project_id=PROJECT_ID, active_only=True)
    steering_scope.execute(
        "UPDATE actor_message_recipients SET state='acknowledged', "
        "seat_session_id=%s, seat_claim_id=%s, delivered_at=%s, acknowledged_at=%s "
        "WHERE message_id='msg-acknowledged'",
        (STEERING_SESSION, int(held[0]["id"]), LONG_AGO, LONG_AGO),
    )
    _release_the_seat(steering_scope)
    steering_scope.execute(
        "UPDATE harness_sessions SET ended_at=%s WHERE session_id=%s",
        (NOW, STEERING_SESSION),
    )
    steering_scope.commit()

    report = _compose(steering_scope, session_id="successor-seat")
    assert report.messages_awaiting_seat == 0
    assert "awaiting a seat" not in report_body(report)

    claim = acquire_steering(
        steering_scope,
        session_id="successor-seat",
        project_id=PROJECT_ID,
        reason="successor seat",
    )
    assert claim["message_handoff"] == {
        "drained_count": 0,
        "parked_count": 0,
        "digest": "",
    }
