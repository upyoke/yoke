"""Repeated hook-lease expiry is a named failure, not an operator who has not typed."""

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
    seed_tool_call,
)
from yoke_contracts.session_control.wake_delivery import delivery_attempt_diagnostic
from yoke_core.domain.steering_fleet_report_delivery_states import (
    ATTEMPT_FAILED,
    AWAITING_ATTEMPT,
    TURN_IN_FLIGHT,
)
from yoke_core.domain.steering_fleet_report_undelivered import undelivered_messages


@pytest.fixture
def fleet(test_db):
    seed_session(test_db, ASKER, last_tool_call_at=BEFORE_THAT)
    seed_session(test_db, ANSWERER, last_tool_call_at=JUST_NOW)
    test_db.commit()
    return test_db


def test_hook_lease_expired_is_the_diagnostic_not_unreported() -> None:
    assert (
        delivery_attempt_diagnostic("hook_lease_expired", {"hook_event": "PreToolUse"})
        == "hook_lease_expired"
    )
    assert delivery_attempt_diagnostic("failed", {}) == "unreported"


def test_repeated_expired_hook_leases_name_the_reason_and_count(fleet) -> None:
    seed_message(fleet, "msg-1", sender=ASKER, to=ANSWERER, at=LONG_AGO)
    for index in range(3):
        seed_delivery_attempt(
            fleet,
            f"attempt-{index}",
            message_id="msg-1",
            to=ANSWERER,
            result_code="hook_lease_expired",
            evidence={"hook_event": "PreToolUse"},
            started_at=JUST_NOW,
            kind="hook",
        )
    fleet.commit()

    rows = undelivered_messages(fleet, project_id=PROJECT_ID, now=NOW)

    assert [entry.delivery_state for entry in rows] == [ATTEMPT_FAILED]
    assert rows[0].diagnostic == "hook_lease_expired ×3"
    assert rows[0].failed_attempt_count == 3
    assert rows[0].needs_seat_action is True


def test_an_in_flight_retry_still_names_the_repeated_refusals(fleet) -> None:
    """The latest attempt may still be open; the count is the earlier misses."""
    seed_message(fleet, "msg-1", sender=ASKER, to=ANSWERER, at=LONG_AGO)
    for index in range(2):
        seed_delivery_attempt(
            fleet,
            f"attempt-{index}",
            message_id="msg-1",
            to=ANSWERER,
            result_code="hook_lease_expired",
            started_at=JUST_NOW,
            kind="hook",
        )
    seed_delivery_attempt(
        fleet,
        "attempt-open",
        message_id="msg-1",
        to=ANSWERER,
        result_code="",
        started_at=NOW,
        kind="hook",
    )
    fleet.commit()

    rows = undelivered_messages(fleet, project_id=PROJECT_ID, now=NOW)

    assert [entry.delivery_state for entry in rows] == [ATTEMPT_FAILED]
    assert rows[0].diagnostic == "hook_lease_expired ×2"
    assert rows[0].failed_attempt_count == 2


def test_an_open_tool_call_does_not_hide_repeated_expired_leases(fleet) -> None:
    seed_message(fleet, "msg-1", sender=ASKER, to=ANSWERER, at=LONG_AGO)
    for index in range(2):
        seed_delivery_attempt(
            fleet,
            f"attempt-{index}",
            message_id="msg-1",
            to=ANSWERER,
            result_code="hook_lease_expired",
            started_at=JUST_NOW,
            kind="hook",
        )
    seed_tool_call(
        fleet,
        ANSWERER,
        tool_use_id="call-1",
        started_at=JUST_NOW,
        command_summary="yoke watch pytest",
    )
    fleet.commit()

    rows = undelivered_messages(fleet, project_id=PROJECT_ID, now=NOW)

    assert [entry.delivery_state for entry in rows] == [ATTEMPT_FAILED]
    assert "hook_lease_expired" in rows[0].diagnostic


def test_a_single_open_call_without_repeated_failure_is_still_in_flight(fleet) -> None:
    seed_message(fleet, "msg-1", sender=ASKER, to=ANSWERER, at=LONG_AGO)
    seed_tool_call(
        fleet,
        ANSWERER,
        tool_use_id="call-1",
        started_at=JUST_NOW,
        command_summary="yoke watch pytest",
    )
    fleet.commit()

    rows = undelivered_messages(fleet, project_id=PROJECT_ID, now=NOW)

    assert [entry.delivery_state for entry in rows] == [TURN_IN_FLIGHT]


def test_an_active_desktop_recipient_is_waiting_on_its_hook_not_its_operator(
    test_db,
) -> None:
    seed_session(
        test_db,
        ANSWERER,
        last_tool_call_at=JUST_NOW,
        executor_surface="cursor-desktop",
    )
    seed_session(test_db, ASKER, last_tool_call_at=BEFORE_THAT)
    seed_message(test_db, "msg-1", sender=ASKER, to=ANSWERER, at=LONG_AGO)
    test_db.commit()

    rows = undelivered_messages(test_db, project_id=PROJECT_ID, now=NOW)

    assert [entry.delivery_state for entry in rows] == [AWAITING_ATTEMPT]
    assert rows[0].operator_wake is True
    assert rows[0].needs_seat_action is False
