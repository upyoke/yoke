"""An in-flight launch is staffing, not unclaimed waiting."""

from __future__ import annotations

import json

import pytest

from runtime.api.steering_fleet_test_helpers import (
    ACTOR_ID,
    JUST_NOW,
    LONG_AGO,
    NOW,
    PROJECT_ID,
    STEERING_SESSION,
    compose as _compose,
    seed_steering_scope,
)
from yoke_core.domain.steering_fleet_report_projection import report_dict
from yoke_core.domain.steering_fleet_report_render import report_body
from yoke_core.domain.steering_fleet_report_render_text import OVERDUE_MARK


@pytest.fixture
def steering_scope(test_db):
    return seed_steering_scope(test_db)


def _available_line(body: str, public_ref: str) -> str:
    return next(
        line
        for line in body.splitlines()
        if f" {public_ref}  " in line and "rank" in line
    )


def _in_flight_launch(
    conn,
    *,
    item_id: int,
    state: str = "assigned",
    created_at: str = JUST_NOW,
    launch_id: str = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
) -> None:
    public_ref = f"YOK-{item_id}"
    message_id = f"msg-{launch_id}"
    conn.execute(
        "INSERT INTO session_messages "
        "(message_id, sender_actor_id, sender_session_id, body, body_sha256, "
        "selector_snapshot, created_at, expires_at) "
        "VALUES (%s, %s, %s, 'launch instruction', 'sha', %s, %s, %s)",
        (
            message_id,
            ACTOR_ID,
            STEERING_SESSION,
            json.dumps({}),
            created_at,
            NOW,
        ),
    )
    conn.execute(
        "INSERT INTO session_launches "
        "(launch_id, requester_actor_id, project_id, requested_surface, "
        "selected_surface, allow_surface_fallback, message_id, state, "
        "deadline_at, created_at, origin, session_name) "
        "VALUES (%s, %s, %s, 'cursor-cli', 'cursor-cli', 0, %s, %s, "
        "%s, %s, 'steering', %s)",
        (
            launch_id,
            ACTOR_ID,
            PROJECT_ID,
            message_id,
            state,
            NOW,
            created_at,
            f"{public_ref}: Unpicked work {item_id}",
        ),
    )
    conn.commit()


def test_an_assigned_launch_stays_available_and_is_not_waiting_to_be_staffed(
    steering_scope,
):
    """Hiding launched items would stall a frozen worker; mislabeling staffs twice."""
    item_id = 1
    _in_flight_launch(steering_scope, item_id=item_id)

    report = _compose(steering_scope)
    launched = next(entry for entry in report.available if entry.item_id == item_id)
    body = report_body(report)
    line = _available_line(body, launched.public_ref)

    assert launched.launch_state == "assigned"
    assert launched.item_id not in {entry.item_id for entry in report.waited_too_long()}
    assert line.lstrip()[:1] != OVERDUE_MARK
    assert "launch assigned" in line
    assert "in flight" in line
    assert "waiting" not in line
    assert "new" not in line


def test_the_clock_for_a_launch_in_flight_starts_at_the_launch(steering_scope):
    item_id = 2
    _in_flight_launch(steering_scope, item_id=item_id, created_at=JUST_NOW)

    report = _compose(steering_scope)
    launched = next(entry for entry in report.available if entry.item_id == item_id)
    projected = next(
        row
        for row in report_dict(report)["available"]
        if row["item_id"] == item_id
    )

    assert launched.waiting_seconds(NOW) == 2 * 60
    assert projected["waiting_seconds"] == 2 * 60
    assert projected["launch_state"] == "assigned"
    assert projected["launched_at"] == JUST_NOW
    assert "in flight 2m" in _available_line(report_body(report), launched.public_ref)


def test_a_long_in_flight_launch_is_visible_as_that_not_as_unstaffed_waiting(
    steering_scope,
):
    item_id = 3
    _in_flight_launch(steering_scope, item_id=item_id, created_at=LONG_AGO)

    report = _compose(steering_scope)
    launched = next(entry for entry in report.available if entry.item_id == item_id)
    line = _available_line(report_body(report), launched.public_ref)

    assert launched.waiting_seconds(NOW) >= report.staffing_after_seconds
    assert launched not in report.waited_too_long()
    assert line.lstrip()[:1] != OVERDUE_MARK
    assert "launch assigned" in line
    assert "in flight" in line
    assert "waiting" not in line


@pytest.mark.parametrize("state", ("launching", "awaiting_registration"))
def test_launching_and_awaiting_registration_are_staffing_in_flight(
    steering_scope, state
):
    item_id = 1
    _in_flight_launch(steering_scope, item_id=item_id, state=state)

    launched = next(
        entry for entry in _compose(steering_scope).available if entry.item_id == item_id
    )

    assert launched.launch_state == state
