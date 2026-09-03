"""Ordinary release, session release, and reactivation for steering claims."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from yoke_core.domain.strategy_docs_defaults import NEAR_TERM_PLAN_SLUG
from runtime.api.domain.steering_claim_test_support import (
    PROJECT_ALPHA,
    SESSION_ALPHA,
    SESSION_BETA,
    acquire_steering,
    seed_strategy_doc,
    seed_standard_steering_world,
)
from yoke_core.domain.sessions_lifecycle_claim import release_claim
from yoke_core.domain.sessions_lifecycle_release_bulk import release_all_claims
from yoke_core.domain.sessions_lifecycle_reactivation_claims import (
    auto_reacquire_session_ended_claims,
)
from yoke_core.domain.sessions_render_end_claim_release import release_session_claims
from yoke_core.domain.sessions_render_reclaim import handoff_claim
from yoke_core.domain.sessions_analytics import SessionError
from yoke_core.domain.strategy_doc_steering_pair import (
    active_paired_session_doc_claim,
)


@pytest.fixture
def steering_db(test_db):
    seed_standard_steering_world(test_db)
    return test_db


def _active_rows(conn, session_id: str):
    return conn.execute(
        "SELECT id, session_id, target_kind, scope "
        "FROM work_claims WHERE session_id=%s AND released_at IS NULL",
        (session_id,),
    ).fetchall()


def test_ordinary_release_emits_event_and_unblocks_project(steering_db) -> None:
    with patch("yoke_core.domain.steering_claims.emit_steering_claimed"):
        first = acquire_steering(
            steering_db,
            SESSION_ALPHA,
            PROJECT_ALPHA,
            document=NEAR_TERM_PLAN_SLUG,
        )
    with patch(
        "yoke_core.domain.sessions_lifecycle_claim_release.emit_steering_released"
    ) as released_event:
        released = release_claim(steering_db, first["id"], reason="steering complete")
    assert released["release_reason"] == "released"
    assert released["document_claim"]["slug"] == NEAR_TERM_PLAN_SLUG
    assert active_paired_session_doc_claim(steering_db, first["id"]) is None
    released_event.assert_called_once()

    with patch("yoke_core.domain.steering_claims.emit_steering_claimed"):
        successor = acquire_steering(
            steering_db,
            SESSION_BETA,
            PROJECT_ALPHA,
            document=NEAR_TERM_PLAN_SLUG,
        )
    assert successor["session_id"] == SESSION_BETA


def test_session_scoped_release_uses_generic_scope_descriptor(steering_db) -> None:
    with patch("yoke_core.domain.steering_claims.emit_steering_claimed"):
        claim = acquire_steering(steering_db, SESSION_ALPHA, PROJECT_ALPHA)
    with patch(
        "yoke_core.domain.sessions_lifecycle_claim_release.emit_steering_released"
    ) as released_event:
        rows = release_session_claims(
            steering_db,
            SESSION_ALPHA,
            active_claim_rows=_active_rows(steering_db, SESSION_ALPHA),
            release_reason="session_ended",
        )
    assert rows == [
        {
            "target_kind": "steering",
            "scope": {"project_id": PROJECT_ALPHA},
            "claim_id": claim["id"],
        }
    ]
    assert active_paired_session_doc_claim(steering_db, claim["id"]) is None
    released_event.assert_called_once()


def test_handoff_refuses_to_split_session_owned_document_pair(steering_db) -> None:
    with patch("yoke_core.domain.steering_claims.emit_steering_claimed"):
        claim = acquire_steering(
            steering_db,
            SESSION_ALPHA,
            PROJECT_ALPHA,
            document=NEAR_TERM_PLAN_SLUG,
        )

    with pytest.raises(SessionError) as exc_info:
        handoff_claim(steering_db, claim["id"], SESSION_BETA)

    assert exc_info.value.code == "STEERING_HANDOFF_UNSUPPORTED"
    assert len(_active_rows(steering_db, SESSION_ALPHA)) == 1
    assert _active_rows(steering_db, SESSION_BETA) == []
    assert active_paired_session_doc_claim(steering_db, claim["id"]) is not None


def test_bulk_work_release_cascades_the_paired_document(steering_db) -> None:
    with patch("yoke_core.domain.steering_claims.emit_steering_claimed"):
        claim = acquire_steering(
            steering_db,
            SESSION_ALPHA,
            PROJECT_ALPHA,
            document=NEAR_TERM_PLAN_SLUG,
        )

    released = release_all_claims(steering_db, SESSION_ALPHA)

    assert released == 1
    assert active_paired_session_doc_claim(steering_db, claim["id"]) is None


def test_recent_reclaimed_claim_reactivates_when_project_is_free(steering_db) -> None:
    seed_strategy_doc(steering_db, PROJECT_ALPHA, "AREA-PLAN")
    with patch("yoke_core.domain.steering_claims.emit_steering_claimed"):
        claim = acquire_steering(
            steering_db,
            SESSION_ALPHA,
            PROJECT_ALPHA,
            document="AREA-PLAN",
        )
    with patch(
        "yoke_core.domain.sessions_lifecycle_claim_release.emit_steering_released"
    ):
        release_claim(steering_db, claim["id"], reason="reclaimed")

    reacquired, conflicts = auto_reacquire_session_ended_claims(
        steering_db,
        SESSION_ALPHA,
        reacquire_window_s=300,
    )
    assert conflicts == []
    assert reacquired[0]["scope"] == {
        "project_id": PROJECT_ALPHA,
        "document": "AREA-PLAN",
    }
    assert len(_active_rows(steering_db, SESSION_ALPHA)) == 1
    document = active_paired_session_doc_claim(
        steering_db, reacquired[0]["new_claim_id"]
    )
    assert document is not None
    assert document["strategy_doc_slug"] == "AREA-PLAN"


def test_reactivation_reports_new_project_holder(steering_db) -> None:
    with patch("yoke_core.domain.steering_claims.emit_steering_claimed"):
        prior = acquire_steering(steering_db, SESSION_ALPHA, PROJECT_ALPHA)
    with patch(
        "yoke_core.domain.sessions_lifecycle_claim_release.emit_steering_released"
    ):
        release_claim(steering_db, prior["id"], reason="reclaimed")
    with patch("yoke_core.domain.steering_claims.emit_steering_claimed"):
        acquire_steering(steering_db, SESSION_BETA, PROJECT_ALPHA)

    reacquired, conflicts = auto_reacquire_session_ended_claims(
        steering_db,
        SESSION_ALPHA,
        reacquire_window_s=300,
    )
    assert reacquired == []
    assert conflicts[0]["holder_session_id"] == SESSION_BETA
