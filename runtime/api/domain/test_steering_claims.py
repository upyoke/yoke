"""Acquisition, identity, serialization, and listing for steering claims."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from yoke_core.domain.strategy_docs_defaults import NEAR_TERM_PLAN_SLUG
from runtime.api.domain.steering_claim_test_support import (
    PROJECT_ALPHA,
    PROJECT_BETA,
    SESSION_ALPHA,
    SESSION_BETA,
    SESSION_GAMMA,
    acquire_steering,
    seed_strategy_doc,
    seed_standard_steering_world,
)
from yoke_core.domain.sessions_analytics import SessionError
from yoke_core.domain.sessions_lifecycle_claim import claim_work
from yoke_core.domain.steering_claims import list_claims
from yoke_core.domain.strategy_doc_steering_pair import (
    active_paired_session_doc_claim,
)
from yoke_core.domain.strategy_execution import acquire_session_doc_claim
from yoke_core.domain.work_claim_targets import make_steering_target


@pytest.fixture
def steering_db(test_db):
    seed_standard_steering_world(test_db)
    return test_db


def test_target_uses_project_only_scope() -> None:
    target = make_steering_target(PROJECT_ALPHA)
    assert target.scope == {"project_id": PROJECT_ALPHA}
    assert target.insert_columns() == {
        "target_kind": "steering",
        "scope": f'{{"project_id":{PROJECT_ALPHA}}}',
    }


def test_document_target_carries_the_document_beside_the_project() -> None:
    target = make_steering_target(PROJECT_ALPHA, "AREA-PLAN")
    assert target.scope == {"project_id": PROJECT_ALPHA, "document": "AREA-PLAN"}
    assert target.document == "AREA-PLAN"
    assert "AREA-PLAN" in target.render()


def test_generic_claim_path_cannot_bypass_project_serialization(steering_db) -> None:
    with pytest.raises(SessionError, match="project-serialized"):
        claim_work(
            steering_db,
            session_id=SESSION_ALPHA,
            target=make_steering_target(PROJECT_ALPHA),
        )


def test_project_seat_covers_the_project_and_locks_no_document(
    steering_db,
) -> None:
    with patch("yoke_core.domain.steering_claims.emit_steering_claimed") as emitted:
        claim = acquire_steering(steering_db, SESSION_ALPHA, PROJECT_ALPHA)

    assert claim["session_id"] == SESSION_ALPHA
    assert claim["target_kind"] == "steering"
    assert claim["scope"] == {"project_id": PROJECT_ALPHA}
    assert claim["document_claim"] is None
    assert active_paired_session_doc_claim(steering_db, claim["id"]) is None
    emitted.assert_called_once()


def test_document_seat_narrows_the_scope_and_takes_the_lock(steering_db) -> None:
    seed_strategy_doc(steering_db, PROJECT_ALPHA, "AREA-PLAN")
    with patch("yoke_core.domain.steering_claims.emit_steering_claimed"):
        claim = acquire_steering(
            steering_db,
            SESSION_ALPHA,
            PROJECT_ALPHA,
            document="AREA-PLAN",
        )
    assert claim["scope"] == {"project_id": PROJECT_ALPHA, "document": "AREA-PLAN"}
    assert claim["document_claim"]["strategy_doc_slug"] == "AREA-PLAN"
    document_claim = active_paired_session_doc_claim(steering_db, claim["id"])
    assert document_claim is not None
    assert document_claim["strategy_doc_slug"] == "AREA-PLAN"
    assert document_claim["owner_kind"] == "session"
    assert document_claim["owner_session_id"] == SESSION_ALPHA


def test_two_document_seats_on_different_documents_coexist(steering_db) -> None:
    seed_strategy_doc(steering_db, PROJECT_ALPHA, "AREA-PLAN")
    with patch("yoke_core.domain.steering_claims.emit_steering_claimed"):
        first = acquire_steering(
            steering_db,
            SESSION_ALPHA,
            PROJECT_ALPHA,
            document=NEAR_TERM_PLAN_SLUG,
        )
        second = acquire_steering(
            steering_db,
            SESSION_BETA,
            PROJECT_ALPHA,
            document="AREA-PLAN",
        )
    assert first["id"] != second["id"]
    assert first["scope"]["document"] == NEAR_TERM_PLAN_SLUG
    assert second["scope"]["document"] == "AREA-PLAN"
    live = list_claims(steering_db, project_id=PROJECT_ALPHA, active_only=True)
    assert sorted(row["scope"]["document"] for row in live) == [
        "AREA-PLAN",
        NEAR_TERM_PLAN_SLUG,
    ]


def test_project_seat_and_document_seat_refuse_each_other(steering_db) -> None:
    seed_strategy_doc(steering_db, PROJECT_ALPHA, "AREA-PLAN")
    with patch("yoke_core.domain.steering_claims.emit_steering_claimed"):
        acquire_steering(steering_db, SESSION_ALPHA, PROJECT_ALPHA)
        with pytest.raises(SessionError) as refusal:
            acquire_steering(
                steering_db,
                SESSION_BETA,
                PROJECT_ALPHA,
                document="AREA-PLAN",
            )
    assert refusal.value.code == "ALREADY_CLAIMED"
    message = str(refusal.value)
    assert SESSION_ALPHA in message
    assert "--doc SLUG" in message


def test_one_session_cannot_hold_two_overlapping_scopes(steering_db) -> None:
    with patch("yoke_core.domain.steering_claims.emit_steering_claimed"):
        acquire_steering(steering_db, SESSION_ALPHA, PROJECT_ALPHA)
        with pytest.raises(SessionError) as refusal:
            acquire_steering(
                steering_db,
                SESSION_ALPHA,
                PROJECT_ALPHA,
                document=NEAR_TERM_PLAN_SLUG,
            )
    assert refusal.value.code == "SCOPE_MISMATCH"
    assert "yoke claims steering release" in str(refusal.value)


def test_document_conflict_rolls_back_the_steering_seat(steering_db) -> None:
    acquire_session_doc_claim(
        steering_db,
        project_id=PROJECT_ALPHA,
        slug=NEAR_TERM_PLAN_SLUG,
        session_id=SESSION_BETA,
        actor_id=2,
    )
    with pytest.raises(SessionError) as refusal:
        acquire_steering(
            steering_db,
            SESSION_ALPHA,
            PROJECT_ALPHA,
            document=NEAR_TERM_PLAN_SLUG,
        )
    assert refusal.value.code == "DOCUMENT_ALREADY_CLAIMED"
    assert list_claims(steering_db, project_id=PROJECT_ALPHA, active_only=True) == []


def test_second_project_claim_refuses_and_names_holder(steering_db) -> None:
    with patch("yoke_core.domain.steering_claims.emit_steering_claimed"):
        acquire_steering(steering_db, SESSION_ALPHA, PROJECT_ALPHA)
        with pytest.raises(SessionError) as refusal:
            acquire_steering(steering_db, SESSION_BETA, PROJECT_ALPHA)
    assert refusal.value.code == "ALREADY_CLAIMED"
    assert SESSION_ALPHA in str(refusal.value)
    assert f"--project {PROJECT_ALPHA} --active-only" in str(refusal.value)


def test_refusal_names_the_holding_actor_and_machine(steering_db) -> None:
    steering_db.execute(
        "UPDATE harness_sessions SET machine_id='studio' WHERE session_id=%s",
        (SESSION_ALPHA,),
    )
    steering_db.commit()
    with patch("yoke_core.domain.steering_claims.emit_steering_claimed"):
        acquire_steering(steering_db, SESSION_ALPHA, PROJECT_ALPHA)
        with pytest.raises(SessionError) as refusal:
            acquire_steering(steering_db, SESSION_BETA, PROJECT_ALPHA)
    message = str(refusal.value)
    assert "on studio" in message
    assert "actor" in message or "ben" in message


def test_listing_names_the_holder_actor_and_machine(steering_db) -> None:
    steering_db.execute(
        "UPDATE harness_sessions SET machine_id='studio' WHERE session_id=%s",
        (SESSION_ALPHA,),
    )
    steering_db.commit()
    with patch("yoke_core.domain.steering_claims.emit_steering_claimed"):
        acquire_steering(steering_db, SESSION_ALPHA, PROJECT_ALPHA)
    row = list_claims(steering_db, project_id=PROJECT_ALPHA, active_only=True)[0]
    assert row["holder_machine"] == "studio"
    assert row["holder_actor_label"]


def test_same_session_reacquire_is_idempotent(steering_db) -> None:
    with patch("yoke_core.domain.steering_claims.emit_steering_claimed"):
        first = acquire_steering(steering_db, SESSION_ALPHA, PROJECT_ALPHA)
        second = acquire_steering(steering_db, SESSION_ALPHA, PROJECT_ALPHA)
    assert second["id"] == first["id"]


def test_different_projects_have_independent_steering_seats(steering_db) -> None:
    with patch("yoke_core.domain.steering_claims.emit_steering_claimed"):
        first = acquire_steering(steering_db, SESSION_ALPHA, PROJECT_ALPHA)
        second = acquire_steering(steering_db, SESSION_GAMMA, PROJECT_BETA)
    assert first["scope"] == {"project_id": PROJECT_ALPHA}
    assert second["scope"] == {"project_id": PROJECT_BETA}


def test_list_filters_by_project_holder_and_active_state(steering_db) -> None:
    with patch("yoke_core.domain.steering_claims.emit_steering_claimed"):
        acquire_steering(steering_db, SESSION_ALPHA, PROJECT_ALPHA)
        acquire_steering(steering_db, SESSION_GAMMA, PROJECT_BETA)
    rows = list_claims(
        steering_db,
        project_id=PROJECT_ALPHA,
        session_id=SESSION_ALPHA,
        active_only=True,
    )
    assert [(row["session_id"], row["scope"]) for row in rows] == [
        (SESSION_ALPHA, {"project_id": PROJECT_ALPHA}),
    ]
