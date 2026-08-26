"""A crashed steering holder cannot leave its project scope bricked."""

from __future__ import annotations

from unittest.mock import patch

from runtime.api.domain.steering_scope_claim_test_support import (
    PROJECT_ALPHA,
    SESSION_ALPHA,
    SESSION_BETA,
    acquire_scope,
    seed_standard_scope_world,
)
from yoke_core.domain.sessions_render_reclaim import reclaim_stale_session


def test_stale_sweep_reclaims_scope_and_another_session_can_acquire(test_db) -> None:
    seed_standard_scope_world(test_db)
    with patch("yoke_core.domain.steering_scope_claims.emit_steering_scope_claimed"):
        abandoned = acquire_scope(
            test_db,
            SESSION_ALPHA,
            PROJECT_ALPHA,
            ["MISSION"],
        )
    with patch(
        "yoke_core.domain.sessions_lifecycle_claim_events.emit_steering_scope_released"
    ) as reclaimed_event:
        reclaim_stale_session(test_db, SESSION_ALPHA)

    row = test_db.execute(
        "SELECT released_at, release_reason FROM work_claims WHERE id=%s",
        (abandoned["id"],),
    ).fetchone()
    assert row["released_at"] is not None
    assert row["release_reason"] == "reclaimed"
    assert reclaimed_event.call_args.kwargs["reclaimed"] is True

    with patch("yoke_core.domain.steering_scope_claims.emit_steering_scope_claimed"):
        successor = acquire_scope(
            test_db,
            SESSION_BETA,
            PROJECT_ALPHA,
            ["MISSION"],
        )
    assert successor["owner_session_id"] == SESSION_BETA
