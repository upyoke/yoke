"""Acquisition, overlap, identity, and listing for steering scopes."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from runtime.api.domain.steering_scope_claim_test_support import (
    PROJECT_ALPHA,
    PROJECT_BETA,
    SESSION_ALPHA,
    SESSION_BETA,
    SESSION_GAMMA,
    acquire_scope,
    seed_standard_scope_world,
)
from yoke_core.domain.sessions_analytics import SessionError
from yoke_core.domain.sessions_lifecycle_claim import claim_work
from yoke_core.domain.steering_scope_claims import list_claims
from yoke_core.domain.work_claim_targets import make_steering_scope_target


@pytest.fixture
def scope_db(test_db):
    seed_standard_scope_world(test_db)
    return test_db


def test_target_canonicalizes_document_scope() -> None:
    target = make_steering_scope_target(
        PROJECT_ALPHA,
        ["VISION", "MISSION", "VISION"],
    )
    assert target.steering_strategy_doc_slugs == ("MISSION", "VISION")
    assert target.insert_columns()["steering_strategy_doc_slugs"] == (
        '["MISSION","VISION"]'
    )


def test_generic_claim_acquire_refuses_to_bypass_scope_serialization(scope_db) -> None:
    target = make_steering_scope_target(PROJECT_ALPHA, ["MISSION"])
    with pytest.raises(SessionError, match="project-serialized"):
        claim_work(scope_db, session_id=SESSION_ALPHA, target=target)


def test_acquire_records_session_authority_and_registration_provenance(
    scope_db,
) -> None:
    with patch(
        "yoke_core.domain.steering_scope_claims.emit_steering_scope_claimed"
    ) as emitted:
        claim = acquire_scope(
            scope_db,
            SESSION_ALPHA,
            PROJECT_ALPHA,
            ["VISION", "MISSION", "VISION"],
        )

    assert claim["target_kind"] == "steering_scope"
    assert claim["steering_strategy_doc_slugs"] == ["MISSION", "VISION"]
    assert claim["owner_kind"] == "session"
    assert claim["owner_session_id"] == SESSION_ALPHA
    assert claim["owner_item_id"] is None
    assert claim["owner_work_claim_id"] is None
    assert claim["registered_by_actor_id"] == 2
    assert claim["registered_by_session_id"] == SESSION_ALPHA
    emitted.assert_called_once()


def test_intersecting_document_sets_refuse_and_name_the_holder(scope_db) -> None:
    with patch("yoke_core.domain.steering_scope_claims.emit_steering_scope_claimed"):
        acquire_scope(
            scope_db,
            SESSION_ALPHA,
            PROJECT_ALPHA,
            ["MISSION", "VISION"],
        )
        with pytest.raises(SessionError) as refusal:
            acquire_scope(
                scope_db,
                SESSION_BETA,
                PROJECT_ALPHA,
                ["VISION"],
            )
    assert refusal.value.code == "ALREADY_CLAIMED"
    assert SESSION_ALPHA in str(refusal.value)
    assert "steering-scope claim" in str(refusal.value)


@pytest.mark.parametrize(
    ("first_scope", "second_scope"),
    (((), ("MISSION",)), (("MISSION",), ())),
)
def test_whole_project_and_document_scope_refuse_in_both_directions(
    scope_db,
    first_scope,
    second_scope,
) -> None:
    with patch("yoke_core.domain.steering_scope_claims.emit_steering_scope_claimed"):
        acquire_scope(scope_db, SESSION_ALPHA, PROJECT_ALPHA, first_scope)
        with pytest.raises(SessionError, match=SESSION_ALPHA):
            acquire_scope(scope_db, SESSION_BETA, PROJECT_ALPHA, second_scope)


def test_disjoint_document_sets_in_one_project_coexist(scope_db) -> None:
    with patch("yoke_core.domain.steering_scope_claims.emit_steering_scope_claimed"):
        first = acquire_scope(scope_db, SESSION_ALPHA, PROJECT_ALPHA, ["MISSION"])
        second = acquire_scope(scope_db, SESSION_BETA, PROJECT_ALPHA, ["VISION"])
    assert first["id"] != second["id"]


def test_whole_project_scopes_in_different_projects_coexist(scope_db) -> None:
    with patch("yoke_core.domain.steering_scope_claims.emit_steering_scope_claimed"):
        first = acquire_scope(scope_db, SESSION_ALPHA, PROJECT_ALPHA)
        second = acquire_scope(scope_db, SESSION_GAMMA, PROJECT_BETA)
    assert first["steering_project_id"] == PROJECT_ALPHA
    assert second["steering_project_id"] == PROJECT_BETA


def test_list_filters_by_project_holder_and_active_state(scope_db) -> None:
    with patch("yoke_core.domain.steering_scope_claims.emit_steering_scope_claimed"):
        acquire_scope(scope_db, SESSION_ALPHA, PROJECT_ALPHA, ["MISSION"])
        acquire_scope(scope_db, SESSION_BETA, PROJECT_ALPHA, ["VISION"])
    rows = list_claims(
        scope_db,
        project_id=PROJECT_ALPHA,
        session_id=SESSION_BETA,
        active_only=True,
    )
    assert [
        (row["owner_session_id"], row["steering_strategy_doc_slugs"]) for row in rows
    ] == [
        (SESSION_BETA, ["VISION"]),
    ]
