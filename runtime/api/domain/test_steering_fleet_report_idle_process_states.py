"""An idle holder's row says when a message reaches its turn.

A headless worker's process exits between turns and the next message resumes
it from its transcript, so none of the resumable states may read as a reason
to terminate.
"""

from __future__ import annotations

import pytest

from runtime.api.steering_fleet_test_helpers import (
    JUST_NOW,
    LONG_AGO,
    STEERING_SESSION,
    WORKER_SESSION,
    compose as _compose,
    seed_delivery_attempt,
    seed_message,
    seed_steering_scope,
)
from yoke_core.domain.sessions_lifecycle_claim import claim_work
from yoke_core.domain.steering_fleet_report_render import report_body
from yoke_core.domain.work_claim_targets import make_item_target

#: A version the codex-cli capability proves for ``message_stopped``.
RESUMABLE_VERSION = "0.200.0"
EXITED_AT = "2026-08-26T11:30:00.000000Z"


@pytest.fixture
def steering_scope(test_db):
    conn = seed_steering_scope(test_db)
    claim_work(conn, session_id=WORKER_SESSION, target=make_item_target(1))
    conn.execute(
        "UPDATE harness_sessions SET turn_posture='running' WHERE session_id=%s",
        (WORKER_SESSION,),
    )
    conn.commit()
    return conn


def _record_exit(conn, *, version: str | None = RESUMABLE_VERSION) -> None:
    conn.execute(
        "UPDATE harness_sessions SET executor_version=%s, "
        "native_process_gone_at=%s, native_process_gone_evidence='{}', "
        "last_heartbeat=%s, last_tool_call_at=%s, episode_started_at=NULL "
        "WHERE session_id=%s",
        (version, EXITED_AT, LONG_AGO, LONG_AGO, WORKER_SESSION),
    )
    conn.commit()


def _holder_line(report) -> str:
    return next(
        line for line in report_body(report).splitlines() if WORKER_SESSION in line
    )


def test_mid_turn_holder_says_the_message_waits(steering_scope):
    report = _compose(steering_scope)

    assert any(row.session_id == WORKER_SESSION for row in report.idle)
    line = _holder_line(report)
    assert "mid-turn — message waits until the turn ends" in line
    assert "yoke say --item YOK-1 --stdin" in line
    assert "terminate" not in line


def test_exited_holder_on_a_resumable_surface_is_messaged_not_terminated(
    steering_scope,
):
    _record_exit(steering_scope)

    report = _compose(steering_scope)
    holder = next(row for row in report.idle if row.session_id == WORKER_SESSION)

    assert holder.native_process_gone is True
    assert holder.resumable_from_transcript is True
    line = _holder_line(report)
    assert "between turns — message wakes it" in line
    assert "yoke say --item YOK-1 --stdin" in line
    assert "terminate" not in line


def test_exited_holder_a_wake_is_resuming_reads_resuming_now(steering_scope):
    _record_exit(steering_scope)
    seed_message(
        steering_scope,
        "message-resume",
        sender=STEERING_SESSION,
        to=WORKER_SESSION,
        at=JUST_NOW,
        state="injected",
    )
    seed_delivery_attempt(
        steering_scope,
        "wake-after-exit",
        message_id="message-resume",
        to=WORKER_SESSION,
        result_code="wake_delivered",
    )
    steering_scope.commit()

    report = _compose(steering_scope)
    holder = next(row for row in report.holders if row.session_id == WORKER_SESSION)

    assert holder.resuming is True
    assert holder.native_process_gone is False
    assert holder.requires_immediate_alarm is False
    line = _holder_line(report)
    assert "message wake in flight — let the turn start" in line
    assert "terminate" not in line


def test_a_wake_from_before_the_exit_does_not_read_as_resuming(steering_scope):
    seed_message(
        steering_scope,
        "message-earlier",
        sender=STEERING_SESSION,
        to=WORKER_SESSION,
        at="2026-08-26T11:00:00.000000Z",
        state="injected",
    )
    seed_delivery_attempt(
        steering_scope,
        "wake-before-exit",
        message_id="message-earlier",
        to=WORKER_SESSION,
        result_code="wake_delivered",
        started_at="2026-08-26T11:00:00.000000Z",
    )
    _record_exit(steering_scope)

    holder = next(
        row
        for row in _compose(steering_scope).holders
        if row.session_id == WORKER_SESSION
    )

    assert holder.resuming is False
    assert holder.native_process_gone is True


def test_exit_on_a_surface_no_message_can_resume_names_operator_input(
    steering_scope,
):
    _record_exit(steering_scope, version=None)

    line = _holder_line(_compose(steering_scope))

    assert "between turns — message needs operator input on this surface" in line


@pytest.mark.parametrize("exited", [False, True])
def test_expected_park_describes_its_wait_with_or_without_a_native(
    exited, steering_scope
):
    if exited:
        _record_exit(steering_scope)
    steering_scope.execute(
        "UPDATE harness_sessions SET mode='parked', quiet_reason='waiting on release', "
        "native_process_gone_evidence=%s WHERE session_id=%s",
        ('{"exit_code":0}', WORKER_SESSION),
    )
    steering_scope.commit()
    line = _holder_line(_compose(steering_scope))
    assert "parked waiting on release" in line
    assert "process running" not in line


def test_containment_with_zero_exit_code_still_alarms_under_a_park(steering_scope):
    _record_exit(steering_scope)
    steering_scope.execute(
        "UPDATE harness_sessions SET mode='parked', native_process_gone_evidence=%s "
        "WHERE session_id=%s",
        ('{"exit_code":0,"containment_reason":"inactivity"}', WORKER_SESSION),
    )
    steering_scope.commit()
    report = _compose(steering_scope)
    holder = next(row for row in report.idle if row.session_id == WORKER_SESSION)
    assert holder.native_process_gone and holder.contained_by_sweep
    assert (
        "contained by sweep: inactivity, claims held; parked waiting"
        in _holder_line(report)
    )


@pytest.mark.parametrize("posture", ["running", "waiting"])
def test_roster_and_holder_share_delivery_state(steering_scope, posture):
    from yoke_core.domain.sessions_list_read import list_sessions

    steering_scope.execute(
        "UPDATE harness_sessions SET turn_posture=%s, executor_version=%s "
        "WHERE session_id=%s",
        (posture, RESUMABLE_VERSION, WORKER_SESSION),
    )
    steering_scope.commit()
    report = _compose(steering_scope)
    holder = next(row for row in report.holders if row.session_id == WORKER_SESSION)
    from yoke_core.domain.steering_fleet_report_projection import report_dict

    assert (
        report_dict(report)["holders"][0]["message_delivery"] == holder.message_delivery
    )
    [roster] = list_sessions(session_id=WORKER_SESSION)
    assert roster["message_delivery"] == holder.message_delivery
    assert (
        "mid-turn" if posture == "running" else "between turns"
    ) in holder.message_delivery
