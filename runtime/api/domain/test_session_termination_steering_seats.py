"""Termination authority is org-wide and frees the target's steering seats."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from runtime.api.domain.steering_claim_test_support import (
    PROJECT_ALPHA,
    PROJECT_BETA,
    SESSION_ALPHA,
    SESSION_BETA,
    SESSION_GAMMA,
    acquire_steering,
    seed_standard_steering_world,
)
from yoke_core.domain.session_control_schema import create_session_control_tables
from yoke_core.domain.session_termination import terminate_session
from yoke_core.domain.sessions_analytics import SessionError
from yoke_core.domain.steering_scope_coverage import live_steering_claims
from yoke_core.domain.strategy_doc_steering_pair import (
    active_paired_session_doc_claim,
)
from yoke_core.domain.strategy_docs_defaults import NEAR_TERM_PLAN_SLUG


@pytest.fixture
def steering_world(test_db, monkeypatch):
    create_session_control_tables(test_db)
    seed_standard_steering_world(test_db)
    test_db.execute(
        "UPDATE harness_sessions SET launch_origin='yoke' WHERE session_id=%s",
        (SESSION_GAMMA,),
    )
    for target in (
        "yoke_core.domain.session_termination.emit_session_terminated",
        "yoke_core.domain.sessions_render_end.emit_release_claims_branch_event",
        "yoke_core.domain.sessions_render_end._sa._emit_session_event",
    ):
        monkeypatch.setattr(target, lambda *args, **kwargs: None)
    with patch("yoke_core.domain.steering_claims.emit_steering_claimed"):
        alpha_seat = acquire_steering(test_db, SESSION_ALPHA, PROJECT_ALPHA)
        beta_seat = acquire_steering(
            test_db,
            SESSION_GAMMA,
            PROJECT_BETA,
            plan_document=NEAR_TERM_PLAN_SLUG,
        )
    test_db.commit()
    return test_db, alpha_seat, beta_seat


def test_seat_on_one_project_terminates_another_projects_seat_holder(
    steering_world,
) -> None:
    conn, _alpha_seat, beta_seat = steering_world
    assert active_paired_session_doc_claim(conn, beta_seat["id"]) is not None

    result = terminate_session(
        conn,
        target_session_id=SESSION_GAMMA,
        actor_id=2,
        caller_session_id=SESSION_ALPHA,
        reason="dead session holding the beta seat",
    )
    conn.commit()

    assert result["session"]["terminated_at"]
    seat = conn.execute(
        "SELECT released_at, release_reason FROM work_claims WHERE id = %s",
        (beta_seat["id"],),
    ).fetchone()
    assert seat["released_at"] and seat["release_reason"] == "session_ended"
    assert active_paired_session_doc_claim(conn, beta_seat["id"]) is None
    assert [
        claim["session_id"]
        for claim in live_steering_claims(conn)
        if int(claim["scope"]["project_id"]) == PROJECT_BETA
    ] == []

    with patch("yoke_core.domain.steering_claims.emit_steering_claimed"):
        successor = acquire_steering(
            conn,
            SESSION_BETA,
            PROJECT_BETA,
            plan_document=NEAR_TERM_PLAN_SLUG,
        )
    assert successor["document_claim"]["strategy_doc_slug"] == NEAR_TERM_PLAN_SLUG


def test_caller_without_any_live_seat_is_refused_with_recovery(
    steering_world,
) -> None:
    conn, _alpha_seat, beta_seat = steering_world

    with pytest.raises(SessionError) as refused:
        terminate_session(
            conn,
            target_session_id=SESSION_GAMMA,
            actor_id=2,
            caller_session_id=SESSION_BETA,
            reason="no seat",
        )

    assert refused.value.code == "TERMINATION_AUTHORITY_REQUIRED"
    assert "live steering seat on any project" in str(refused.value)
    assert "yoke claims steering acquire" in str(refused.value)
    conn.rollback()
    assert (
        conn.execute(
            "SELECT released_at FROM work_claims WHERE id = %s",
            (beta_seat["id"],),
        ).fetchone()["released_at"]
        is None
    )
