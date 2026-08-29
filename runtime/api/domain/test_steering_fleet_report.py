"""What the fleet report notices, and what it deliberately stays quiet about."""

from __future__ import annotations

import pytest

from runtime.api.steering_fleet_test_helpers import (
    JUST_NOW,
    LONG_AGO,
    NOW,
    SURFACE,
    WORKER_SESSION,
    compose as _compose,
    seed_steering_scope,
)
from yoke_core.domain.session_activity_state import apply_envelope_state
from yoke_core.domain.session_mode import SESSION_MODE_PARKED, set_session_mode
from yoke_core.domain.sessions_lifecycle_claim import claim_work
from yoke_core.domain.work_claim_targets import make_item_target


@pytest.fixture
def steering_scope(test_db):
    return seed_steering_scope(test_db)


def test_work_nobody_ever_picked_up_is_available_and_marked_never_started(
    steering_scope,
):
    report = _compose(steering_scope)

    assert {entry.item_id for entry in report.available} == {1, 2, 3}
    assert not any(entry.was_owned for entry in report.available)
    assert {entry.item_id for entry in report.waited_too_long()} == {1, 2, 3}
    assert report.actionable is True


def test_work_whose_owner_was_released_stays_in_one_list_marked_stopped(
    steering_scope,
):
    claim_work(
        steering_scope,
        session_id=WORKER_SESSION,
        target=make_item_target(2),
    )
    steering_scope.execute(
        "UPDATE work_claims SET released_at = %s, release_reason = 'reclaimed' "
        "WHERE session_id = %s",
        (LONG_AGO, WORKER_SESSION),
    )
    steering_scope.commit()

    report = _compose(steering_scope)

    stopped = {entry.item_id for entry in report.available if entry.was_owned}
    never_started = {entry.item_id for entry in report.available if not entry.was_owned}
    assert stopped == {2}
    assert never_started == {1, 3}


def test_a_claim_released_moments_ago_is_available_but_not_overdue(steering_scope):
    claim_work(
        steering_scope,
        session_id=WORKER_SESSION,
        target=make_item_target(2),
    )
    steering_scope.execute(
        "UPDATE work_claims SET released_at = %s, release_reason = 'released' "
        "WHERE session_id = %s",
        (JUST_NOW, WORKER_SESSION),
    )
    steering_scope.commit()

    report = _compose(steering_scope)

    assert 2 in {entry.item_id for entry in report.available}
    assert 2 not in {entry.item_id for entry in report.waited_too_long()}


def test_work_someone_holds_is_not_available(steering_scope):
    for item_id in (1, 2, 3):
        claim_work(
            steering_scope,
            session_id=WORKER_SESSION,
            target=make_item_target(item_id),
        )

    report = _compose(steering_scope)

    assert report.available == ()
    assert report.waited_too_long() == ()
    assert {holder.item_id for holder in report.holders} == {1, 2, 3}


def test_a_quiet_holder_reports_as_idle(steering_scope):
    claim_work(
        steering_scope,
        session_id=WORKER_SESSION,
        target=make_item_target(1),
    )

    report = _compose(steering_scope)

    assert {holder.item_id for holder in report.idle} == {1}
    assert report.idle[0].session_id == WORKER_SESSION


def test_staffing_and_idle_thresholds_answer_separate_questions(steering_scope):
    """A holder quiet for ten minutes is working; work unstaffed that long is not."""
    claim_work(
        steering_scope,
        session_id=WORKER_SESSION,
        target=make_item_target(1),
    )
    steering_scope.execute(
        "UPDATE harness_sessions SET last_tool_call_at = %s WHERE session_id = %s",
        ("2026-08-26T11:50:00Z", WORKER_SESSION),
    )
    steering_scope.commit()

    report = _compose(steering_scope)

    assert report.idle == ()
    assert {entry.item_id for entry in report.waited_too_long()} == {2, 3}


def test_a_parked_holder_declared_its_wait_and_is_not_idle(steering_scope):
    claim_work(
        steering_scope,
        session_id=WORKER_SESSION,
        target=make_item_target(1),
    )
    set_session_mode(
        steering_scope,
        WORKER_SESSION,
        SESSION_MODE_PARKED,
        reason="waiting on a blocking claim",
    )
    apply_envelope_state(
        steering_scope,
        {
            "event_name": "HarnessToolCallStarted",
            "session_id": WORKER_SESSION,
            "event_time": NOW,
            "tool_use_id": "tool-1",
            "tool_name": "Shell",
        },
    )

    report = _compose(steering_scope)

    assert report.idle == ()
    assert {holder.item_id for holder in report.holders} == {1}
    assert report.holders[0].parked is True


def test_an_ended_session_is_not_a_holder_at_all(steering_scope):
    claim_work(
        steering_scope,
        session_id=WORKER_SESSION,
        target=make_item_target(1),
    )
    steering_scope.execute(
        "UPDATE harness_sessions SET ended_at = %s WHERE session_id = %s",
        (JUST_NOW, WORKER_SESSION),
    )
    steering_scope.commit()

    report = _compose(steering_scope)

    assert report.holders == ()
    assert report.idle == ()


def test_launchability_names_the_connected_machine_and_surface(steering_scope):
    report = _compose(steering_scope)

    assert (
        "machine-1",
        SURFACE,
    ) in {(ready.machine_id, ready.surface) for ready in report.launchable}


def test_the_fingerprint_ignores_how_old_everything_is(steering_scope):
    early = _compose(steering_scope)
    later = _compose(steering_scope, now="2026-08-26T12:30:00Z")

    assert early.fingerprint() == later.fingerprint()


def test_a_frozen_item_is_not_reported_as_available(steering_scope):
    """The operator's hold flag is the mechanism; the report does not guess."""
    steering_scope.execute("UPDATE items SET frozen = 1 WHERE id = 2")
    steering_scope.commit()

    report = _compose(steering_scope)

    assert 2 not in {entry.item_id for entry in report.available}
    assert {entry.item_id for entry in report.available} == {1, 3}


def test_an_operator_blocked_item_is_not_reported_as_available(steering_scope):
    steering_scope.execute(
        "UPDATE items SET blocked = 1, blocked_reason = 'held for a decision' "
        "WHERE id = 3"
    )
    steering_scope.commit()

    report = _compose(steering_scope)

    assert 3 not in {entry.item_id for entry in report.available}
