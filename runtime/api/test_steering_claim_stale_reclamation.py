"""A steering holder retains its seat until explicit session end."""

from __future__ import annotations

from unittest.mock import patch

from runtime.api.domain.steering_claim_test_support import (
    PROJECT_ALPHA,
    SESSION_ALPHA,
    SESSION_BETA,
    acquire_steering,
    seed_standard_steering_world,
)
from yoke_core.domain.sessions_render_end import end_session


def test_explicit_end_releases_seat_for_another_session(test_db) -> None:
    seed_standard_steering_world(test_db)
    with patch("yoke_core.domain.steering_claims.emit_steering_claimed"):
        abandoned = acquire_steering(test_db, SESSION_ALPHA, PROJECT_ALPHA)
    with patch(
        "yoke_core.domain.sessions_lifecycle_claim_events.emit_steering_released"
    ):
        end_session(test_db, SESSION_ALPHA)

    row = test_db.execute(
        "SELECT released_at, release_reason FROM work_claims WHERE id=%s",
        (abandoned["id"],),
    ).fetchone()
    assert row["released_at"] is not None
    assert row["release_reason"] == "session_ended"

    with patch("yoke_core.domain.steering_claims.emit_steering_claimed"):
        successor = acquire_steering(test_db, SESSION_BETA, PROJECT_ALPHA)
    assert successor["session_id"] == SESSION_BETA
