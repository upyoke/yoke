"""Acquisition, identity, serialization, and listing for steering claims."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from yoke_contracts.steering_claims import DEFAULT_STEERING_DOC_SLUG
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


def test_generic_claim_path_cannot_bypass_project_serialization(steering_db) -> None:
    with pytest.raises(SessionError, match="project-serialized"):
        claim_work(
            steering_db,
            session_id=SESSION_ALPHA,
            target=make_steering_target(PROJECT_ALPHA),
        )


def test_acquire_records_session_owned_project_scope(steering_db) -> None:
    with patch("yoke_core.domain.steering_claims.emit_steering_claimed") as emitted:
        claim = acquire_steering(steering_db, SESSION_ALPHA, PROJECT_ALPHA)

    assert claim["session_id"] == SESSION_ALPHA
    assert claim["target_kind"] == "steering"
    assert claim["scope"] == {"project_id": PROJECT_ALPHA}
    assert "owner_kind" not in claim
    assert "registered_by_actor_id" not in claim
    document_claim = active_paired_session_doc_claim(steering_db, claim["id"])
    assert document_claim is not None
    assert document_claim["strategy_doc_slug"] == DEFAULT_STEERING_DOC_SLUG
    assert document_claim["owner_kind"] == "session"
    assert document_claim["owner_session_id"] == SESSION_ALPHA
    emitted.assert_called_once()


def test_explicit_document_replaces_the_default_selection(steering_db) -> None:
    seed_strategy_doc(steering_db, PROJECT_ALPHA, "AREA-PLAN")
    with patch("yoke_core.domain.steering_claims.emit_steering_claimed"):
        claim = acquire_steering(
            steering_db,
            SESSION_ALPHA,
            PROJECT_ALPHA,
            doc_slug="AREA-PLAN",
        )
    assert claim["document_claim"]["strategy_doc_slug"] == "AREA-PLAN"
    document_claim = active_paired_session_doc_claim(steering_db, claim["id"])
    assert document_claim is not None
    assert document_claim["strategy_doc_slug"] == "AREA-PLAN"
    assert document_claim["owner_kind"] == "session"
    assert document_claim["owner_session_id"] == SESSION_ALPHA
    with pytest.raises(SessionError) as refusal:
        acquire_steering(
            steering_db,
            SESSION_ALPHA,
            PROJECT_ALPHA,
            doc_slug=DEFAULT_STEERING_DOC_SLUG,
        )
    assert refusal.value.code == "DOCUMENT_MISMATCH"
    assert "AREA-PLAN" in str(refusal.value)


def test_document_conflict_rolls_back_the_steering_seat(steering_db) -> None:
    acquire_session_doc_claim(
        steering_db,
        project_id=PROJECT_ALPHA,
        slug=DEFAULT_STEERING_DOC_SLUG,
        session_id=SESSION_BETA,
        actor_id=2,
    )
    with pytest.raises(SessionError) as refusal:
        acquire_steering(steering_db, SESSION_ALPHA, PROJECT_ALPHA)
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
