"""A crashed steering holder cannot leave its project seat bricked."""

from __future__ import annotations

from unittest.mock import patch

from runtime.api.domain.steering_claim_test_support import (
    PROJECT_ALPHA,
    SESSION_ALPHA,
    SESSION_BETA,
    acquire_steering,
    seed_standard_steering_world,
)
from yoke_core.domain.sessions_render_reclaim import reclaim_stale_session


def test_stale_sweep_reclaims_seat_and_another_session_can_acquire(test_db) -> None:
    seed_standard_steering_world(test_db)
    with patch("yoke_core.domain.steering_claims.emit_steering_claimed"):
        abandoned = acquire_steering(test_db, SESSION_ALPHA, PROJECT_ALPHA)
    with patch(
        "yoke_core.domain.sessions_lifecycle_claim_events.emit_steering_released"
    ) as reclaimed_event:
        reclaim_stale_session(test_db, SESSION_ALPHA)

    row = test_db.execute(
        "SELECT released_at, release_reason FROM work_claims WHERE id=%s",
        (abandoned["id"],),
    ).fetchone()
    assert row["released_at"] is not None
    assert row["release_reason"] == "reclaimed"
    assert reclaimed_event.call_args.kwargs["reclaimed"] is True

    with patch("yoke_core.domain.steering_claims.emit_steering_claimed"):
        successor = acquire_steering(test_db, SESSION_BETA, PROJECT_ALPHA)
    assert successor["session_id"] == SESSION_BETA
