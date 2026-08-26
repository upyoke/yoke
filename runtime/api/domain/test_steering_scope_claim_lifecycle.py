"""Ordinary release, session release, and reactivation for steering claims."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from runtime.api.domain.steering_scope_claim_test_support import (
    PROJECT_ALPHA,
    SESSION_ALPHA,
    SESSION_BETA,
    acquire_scope,
    seed_standard_scope_world,
)
from yoke_core.domain.sessions_lifecycle_claim import release_claim
from yoke_core.domain.sessions_lifecycle_reactivation_claims import (
    auto_reacquire_session_ended_claims,
)
from yoke_core.domain.sessions_render_end_claim_release import release_session_claims


@pytest.fixture
def scope_db(test_db):
    seed_standard_scope_world(test_db)
    return test_db


def _active_rows(conn, session_id: str):
    return conn.execute(
        "SELECT id, target_kind, item_id, epic_id, task_num, process_key, "
        "conflict_group, steering_project_id, steering_strategy_doc_slugs, "
        "owner_session_id "
        "FROM work_claims WHERE session_id=%s AND released_at IS NULL",
        (session_id,),
    ).fetchall()


def test_ordinary_release_emits_steering_event_and_unblocks_scope(scope_db) -> None:
    with patch("yoke_core.domain.steering_scope_claims.emit_steering_scope_claimed"):
        first = acquire_scope(scope_db, SESSION_ALPHA, PROJECT_ALPHA)
    with patch(
        "yoke_core.domain.sessions_lifecycle_claim_release.emit_steering_scope_released"
    ) as released_event:
        released = release_claim(
            scope_db,
            first["id"],
            reason="steering complete",
        )
    assert released["release_reason"] == "released"
    released_event.assert_called_once()

    with patch("yoke_core.domain.steering_scope_claims.emit_steering_scope_claimed"):
        successor = acquire_scope(scope_db, SESSION_BETA, PROJECT_ALPHA, ["MISSION"])
    assert successor["owner_session_id"] == SESSION_BETA


def test_session_scoped_release_uses_typed_steering_target(scope_db) -> None:
    with patch("yoke_core.domain.steering_scope_claims.emit_steering_scope_claimed"):
        claim = acquire_scope(scope_db, SESSION_ALPHA, PROJECT_ALPHA, ["MISSION"])
    with patch(
        "yoke_core.domain.sessions_lifecycle_claim_release.emit_steering_scope_released"
    ) as released_event:
        rows = release_session_claims(
            scope_db,
            SESSION_ALPHA,
            active_claim_rows=_active_rows(scope_db, SESSION_ALPHA),
            release_reason="session_ended",
        )
    assert rows == [
        {
            "target_kind": "steering_scope",
            "steering_project_id": PROJECT_ALPHA,
            "steering_strategy_doc_slugs": ["MISSION"],
            "claim_id": claim["id"],
        }
    ]
    released_event.assert_called_once()


def test_recent_reclaimed_scope_reactivates_when_still_free(scope_db) -> None:
    with patch("yoke_core.domain.steering_scope_claims.emit_steering_scope_claimed"):
        claim = acquire_scope(scope_db, SESSION_ALPHA, PROJECT_ALPHA, ["VISION"])
    with patch(
        "yoke_core.domain.sessions_lifecycle_claim_release.emit_steering_scope_released"
    ):
        release_claim(scope_db, claim["id"], reason="reclaimed")

    reacquired, conflicts = auto_reacquire_session_ended_claims(
        scope_db,
        SESSION_ALPHA,
        reacquire_window_s=300,
    )
    assert conflicts == []
    assert reacquired[0]["steering_project_id"] == PROJECT_ALPHA
    active = _active_rows(scope_db, SESSION_ALPHA)
    assert active[0]["owner_session_id"] == SESSION_ALPHA


def test_reactivation_reports_intersecting_new_holder(scope_db) -> None:
    with patch("yoke_core.domain.steering_scope_claims.emit_steering_scope_claimed"):
        prior = acquire_scope(scope_db, SESSION_ALPHA, PROJECT_ALPHA)
    with patch(
        "yoke_core.domain.sessions_lifecycle_claim_release.emit_steering_scope_released"
    ):
        release_claim(scope_db, prior["id"], reason="reclaimed")
    with patch("yoke_core.domain.steering_scope_claims.emit_steering_scope_claimed"):
        acquire_scope(scope_db, SESSION_BETA, PROJECT_ALPHA, ["VISION"])

    reacquired, conflicts = auto_reacquire_session_ended_claims(
        scope_db,
        SESSION_ALPHA,
        reacquire_window_s=300,
    )
    assert reacquired == []
    assert conflicts[0]["holder_session_id"] == SESSION_BETA
