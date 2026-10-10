"""A queued wake is offered for release only once the wake command takes it.

The wake command releases an unattempted explicit wake only after that
receipt has waited out the wake grace, and refuses as in flight while any
younger one remains. A row that offered the release earlier taught a
command that would be refused, so a young queued wake names when it becomes
releasable instead.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from runtime.api.steering_fleet_test_helpers import (
    ANSWERER,
    ASKER,
    BEFORE_THAT,
    JUST_NOW,
    LONG_AGO,
    NOW,
    PROJECT_ID,
    seed_message,
    seed_session,
)
from yoke_contracts.session_control.wake import EXPLICIT_WAKE_ROUTING_FLAG
from yoke_core.domain.session_message_authorization import project_policy
from yoke_contracts.timestamps import format_instant, parse_instant
from yoke_core.domain.db_helpers import instant_parameter
from yoke_core.domain.session_message_types import parse_timestamp
from yoke_core.domain.steering_fleet_report_delivery_states import NEVER_ATTEMPTED
from yoke_core.domain.steering_fleet_report_undelivered import undelivered_messages


@pytest.fixture
def fleet(test_db):
    """Two ordinary workers, quiet since before any message was sent."""
    seed_session(test_db, ASKER, last_tool_call_at=BEFORE_THAT)
    seed_session(test_db, ANSWERER, last_tool_call_at=BEFORE_THAT)
    test_db.commit()
    return test_db


def _queued_wake(conn, message_id: str, *, at: str | datetime) -> None:
    seed_message(
        conn,
        message_id,
        sender=ASKER,
        to=ANSWERER,
        at=at,
        routing_snapshot={EXPLICIT_WAKE_ROUTING_FLAG: True},
    )


def _releasable_at(conn, sent_at: str | datetime) -> datetime:
    grace = project_policy(conn, PROJECT_ID).wake_ack_grace_seconds
    return parse_timestamp(sent_at) + timedelta(seconds=grace)


def test_a_queued_wake_inside_its_grace_names_when_it_becomes_releasable(fleet):
    _queued_wake(fleet, "msg-young", at=JUST_NOW)
    fleet.commit()

    rows = undelivered_messages(fleet, project_id=PROJECT_ID, now=NOW)

    assert rows[0].delivery_state == NEVER_ATTEMPTED
    assert rows[0].queued_wake is False
    assert rows[0].wake_releasable_at == _releasable_at(fleet, JUST_NOW)


def test_a_queued_wake_past_its_grace_is_offered_for_release(fleet):
    _queued_wake(fleet, "msg-aged", at=LONG_AGO)
    fleet.commit()

    rows = undelivered_messages(fleet, project_id=PROJECT_ID, now=NOW)

    assert rows[0].queued_wake is True
    assert rows[0].wake_releasable_at is None


def test_a_younger_queued_wake_holds_back_the_release_of_an_older_one(fleet):
    """The command refuses while any queued wake is young, so the row waits."""
    _queued_wake(fleet, "msg-aged", at=LONG_AGO)
    _queued_wake(fleet, "msg-young", at=JUST_NOW)
    fleet.commit()

    rows = undelivered_messages(fleet, project_id=PROJECT_ID, now=NOW)

    queued = [row for row in rows if row.delivery_state == NEVER_ATTEMPTED]
    assert [row.queued_wake for row in queued] == [False]
    assert queued[0].wake_releasable_at == _releasable_at(fleet, JUST_NOW)


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kolkata"])
@pytest.mark.parametrize("micros", [0, 123456])
def test_queued_wake_keeps_native_release_until_text_projection(fleet, zone, micros):
    from yoke_core.domain.steering_fleet_report_render_undelivered import _state_phrase

    sent = parse_instant(f"1970-01-01T05:24:00.{micros:06d}+05:30")
    current = sent + timedelta(seconds=120)
    fleet.execute("SELECT set_config('TimeZone', %s, false)", (zone,))
    fleet.execute(
        "UPDATE harness_sessions SET last_tool_call_at=%s WHERE session_id=%s",
        (instant_parameter(fleet, sent - timedelta(hours=2)), ANSWERER),
    )
    _queued_wake(fleet, "msg-precise", at=sent)
    fleet.commit()
    assert fleet.execute("SHOW TimeZone").fetchone()[0] == zone

    row = undelivered_messages(fleet, project_id=PROJECT_ID, now=current)[0]
    expected = _releasable_at(fleet, sent)
    assert row.delivery_state == NEVER_ATTEMPTED
    assert row.queued_wake is False
    assert isinstance(row.wake_releasable_at, datetime)
    assert row.wake_releasable_at.tzinfo == timezone.utc
    assert row.wake_releasable_at == expected
    assert row.wake_releasable_at.microsecond == micros
    assert format_instant(expected) in _state_phrase(row)
