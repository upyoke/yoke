"""An idle holder's row says which process state it is in and what to do.

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
EXITED_AT = "2026-08-26T11:30:00Z"


@pytest.fixture
def steering_scope(test_db):
    conn = seed_steering_scope(test_db)
    claim_work(conn, session_id=WORKER_SESSION, target=make_item_target(1))
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


def test_live_idle_holder_reads_process_running_and_message_it(steering_scope):
    report = _compose(steering_scope)

    assert any(row.session_id == WORKER_SESSION for row in report.idle)
    line = _holder_line(report)
    assert "idle, process running — message it" in line
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
    assert "idle, process exited — message it to resume from transcript" in line
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
    assert f"resuming now (wake started {JUST_NOW}" in line
    assert "terminate" not in line


def test_a_wake_from_before_the_exit_does_not_read_as_resuming(steering_scope):
    seed_message(
        steering_scope,
        "message-earlier",
        sender=STEERING_SESSION,
        to=WORKER_SESSION,
        at="2026-08-26T11:00:00Z",
        state="injected",
    )
    seed_delivery_attempt(
        steering_scope,
        "wake-before-exit",
        message_id="message-earlier",
        to=WORKER_SESSION,
        result_code="wake_delivered",
        started_at="2026-08-26T11:00:00Z",
    )
    _record_exit(steering_scope)

    holder = next(
        row
        for row in _compose(steering_scope).holders
        if row.session_id == WORKER_SESSION
    )

    assert holder.resuming is False
    assert holder.native_process_gone is True


def test_exit_on_a_surface_no_message_can_resume_keeps_terminate_wording(
    steering_scope,
):
    _record_exit(steering_scope, version=None)

    line = _holder_line(_compose(steering_scope))

    assert "this surface cannot resume by message" in line
    assert "terminate deliberately if dead" in line
