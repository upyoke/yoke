"""A dead wrapper is visible; a healthy or completed wrapper stays quiet."""

from __future__ import annotations

from datetime import datetime, timezone

from runtime.api.steering_fleet_test_helpers import (
    LONG_AGO,
    WORKER_SESSION,
    compose,
    seed_steering_scope,
)
from yoke_core.domain.session_background_waiter import (
    arm_background_waiter,
    complete_background_waiter,
    pulse_background_waiter,
)
from yoke_core.domain.sessions_lifecycle_claim import claim_work
from yoke_core.domain.work_claim_targets import make_item_target


def _claimed_waiter(conn) -> None:
    seed_steering_scope(conn)
    claim_work(conn, session_id=WORKER_SESSION, target=make_item_target(1))
    arm_background_waiter(
        conn,
        WORKER_SESSION,
        waiter_id="wait-1",
        kind="qa_case",
        watched_fact="watch_qa_case completion",
        now=datetime(2026, 8, 26, 9, 0, tzinfo=timezone.utc),
    )


def test_missed_deadline_without_completion_is_actionable(test_db) -> None:
    _claimed_waiter(test_db)

    report = compose(test_db)

    assert report.actionable is True
    assert len(report.overdue_waiters) == 1
    waiter = report.overdue_waiters[0]
    assert waiter.public_ref == "YOK-1"
    assert waiter.watched_fact == "watch_qa_case completion"
    assert waiter.armed_at == LONG_AGO
    assert waiter.expected_by == "2026-08-26T09:03:00Z"


def test_healthy_long_wait_raises_nothing(test_db) -> None:
    _claimed_waiter(test_db)
    pulse_background_waiter(
        test_db,
        WORKER_SESSION,
        waiter_id="wait-1",
        now=datetime(2026, 8, 26, 11, 59, tzinfo=timezone.utc),
    )

    assert compose(test_db).overdue_waiters == ()


def test_completed_waiter_raises_nothing(test_db) -> None:
    _claimed_waiter(test_db)
    complete_background_waiter(
        test_db,
        WORKER_SESSION,
        waiter_id="wait-1",
        now=datetime(2026, 8, 26, 9, 5, tzinfo=timezone.utc),
    )

    assert compose(test_db).overdue_waiters == ()
