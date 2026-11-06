"""Exited steering holders yield their seats without reclaim detours."""

from datetime import timedelta
import json


import pytest

from runtime.api.domain.steering_claim_test_support import (
    HUMAN_ACTOR_ID,
    PROJECT_ALPHA,
    SESSION_ALPHA,
    SESSION_BETA,
    acquire_steering,
    seed_standard_steering_world,
)
from yoke_contracts.timestamps import utc_now
from yoke_contracts.session_control.capabilities import capability_for_surface
from yoke_core.domain.db_helpers import instant_parameter
from yoke_core.domain.actor_permissions import (
    ROLE_OPERATOR,
    grant_actor_project_role,
    seed_roles_and_permissions,
)
from yoke_core.domain.sessions_analytics import SessionError
from yoke_core.domain.strategy_docs_defaults import NEAR_TERM_PLAN_SLUG
from yoke_core.domain.strategy_doc_steering_pair import active_paired_session_doc_claim


@pytest.fixture
def seat_db(test_db):
    seed_standard_steering_world(test_db)
    seed_roles_and_permissions(test_db)
    grant_actor_project_role(
        test_db,
        actor_id=HUMAN_ACTOR_ID,
        project_id=PROJECT_ALPHA,
        role_name=ROLE_OPERATOR,
    )
    test_db.execute(
        "UPDATE harness_sessions SET executor_surface='codex-cli', "
        "executor_version='0.161.0'"
    )
    test_db.commit()
    return test_db


@pytest.mark.parametrize("stamp", ["ended_at", "terminated_at"])
@pytest.mark.parametrize("document", [None, NEAR_TERM_PLAN_SLUG])
def test_exited_holder_yields_seat_and_paired_lock(seat_db, stamp, document):
    old = acquire_steering(
        seat_db,
        SESSION_ALPHA,
        PROJECT_ALPHA,
        document=document,
        plan_document=None if document else NEAR_TERM_PLAN_SLUG,
    )
    seat_db.execute(
        f"UPDATE harness_sessions SET {stamp}=%s WHERE session_id=%s",
        (instant_parameter(seat_db, utc_now()), SESSION_ALPHA),
    )
    seat_db.commit()
    new = acquire_steering(
        seat_db,
        SESSION_BETA,
        PROJECT_ALPHA,
        document=document,
        plan_document=None if document else NEAR_TERM_PLAN_SLUG,
    )
    assert new["session_id"] == SESSION_BETA
    assert new["document_claim"]["owner_session_id"] == SESSION_BETA
    assert active_paired_session_doc_claim(seat_db, old["id"]) is None
    released = seat_db.execute(
        "SELECT released_at, release_reason_intent FROM work_claims WHERE id=%s",
        (old["id"],),
    ).fetchone()
    assert released["released_at"] is not None
    assert f"taken over by session {SESSION_BETA}" in released["release_reason_intent"]


def test_live_holder_refusal_names_contact(seat_db):
    acquire_steering(seat_db, SESSION_ALPHA, PROJECT_ALPHA)
    with pytest.raises(SessionError) as refusal:
        acquire_steering(seat_db, SESSION_BETA, PROJECT_ALPHA)
    assert refusal.value.code == "ALREADY_CLAIMED"
    assert f"yoke say --session {SESSION_ALPHA}" in str(refusal.value)


SURFACES = [
    "claude-cli",
    "codex-cli",
    "cursor-cli",
    "claude-desktop",
    "codex-desktop",
    "cursor-desktop",
]


def _record_exit(conn, *, surface, clean=False, later_tool=False):
    now = utc_now()
    conn.execute(
        "UPDATE harness_sessions SET executor_surface=%s, executor_version=%s, mode=%s, "
        "native_process_gone_at=%s, native_process_gone_evidence=%s, "
        "last_tool_call_at=%s WHERE session_id=%s",
        (
            surface,
            capability_for_surface(surface).minimum_version,
            "parked" if clean else "wait",
            instant_parameter(conn, now),
            json.dumps({"exit_code": 0 if clean else 1}),
            instant_parameter(conn, now + timedelta(seconds=1)) if later_tool else None,
            SESSION_ALPHA,
        ),
    )
    conn.commit()


@pytest.mark.parametrize("surface", SURFACES)
def test_confirmed_exit_yields_on_every_surface(seat_db, surface):
    old = acquire_steering(seat_db, SESSION_ALPHA, PROJECT_ALPHA)
    _record_exit(seat_db, surface=surface)
    new = acquire_steering(seat_db, SESSION_BETA, PROJECT_ALPHA)
    assert new["id"] != old["id"]


@pytest.mark.parametrize("surface", ["claude-cli", "codex-cli", "cursor-cli"])
def test_native_worker_between_turns_keeps_seat(seat_db, surface):
    old = acquire_steering(seat_db, SESSION_ALPHA, PROJECT_ALPHA)
    _record_exit(seat_db, surface=surface, clean=True)
    with pytest.raises(SessionError, match="already held"):
        acquire_steering(seat_db, SESSION_BETA, PROJECT_ALPHA)
    assert acquire_steering(seat_db, SESSION_ALPHA, PROJECT_ALPHA)["id"] == old["id"]


@pytest.mark.parametrize("surface", SURFACES)
def test_later_activity_protects_holder(seat_db, surface):
    acquire_steering(seat_db, SESSION_ALPHA, PROJECT_ALPHA)
    _record_exit(seat_db, surface=surface, later_tool=True)
    with pytest.raises(SessionError, match="already held"):
        acquire_steering(seat_db, SESSION_BETA, PROJECT_ALPHA)


def test_heartbeat_silence_does_not_yield_seat(seat_db):
    old = acquire_steering(seat_db, SESSION_ALPHA, PROJECT_ALPHA)
    seat_db.execute(
        "UPDATE harness_sessions SET last_heartbeat=%s WHERE session_id=%s",
        (instant_parameter(seat_db, utc_now() - timedelta(days=30)), SESSION_ALPHA),
    )
    seat_db.commit()
    with pytest.raises(SessionError, match="already held"):
        acquire_steering(seat_db, SESSION_BETA, PROJECT_ALPHA)
    assert acquire_steering(seat_db, SESSION_ALPHA, PROJECT_ALPHA)["id"] == old["id"]


@pytest.mark.parametrize("surface", SURFACES)
def test_resumed_holder_receives_takeover_notice_at_next_hook(seat_db, surface):
    from yoke_core.domain.session_message_delivery import lease_for_hook

    acquire_steering(seat_db, SESSION_ALPHA, PROJECT_ALPHA)
    _record_exit(seat_db, surface=surface)
    acquire_steering(seat_db, SESSION_BETA, PROJECT_ALPHA)
    capability = capability_for_surface(surface)
    receipt = lease_for_hook(
        seat_db,
        session_id=SESSION_ALPHA,
        hook_event=capability.inject_events[0],
        limit=10,
    )
    assert receipt is not None
    assert len(receipt["messages"]) == 1
    body = receipt["messages"][0]["body"]
    assert SESSION_BETA in body
    assert "taken over" in body
    assert "Reacquire" in body


def test_resume_in_flight_protects_exited_holder(seat_db):
    from yoke_contracts.session_control.models import RecipientSelector
    from yoke_core.domain.session_message_service import send_message

    acquire_steering(seat_db, SESSION_ALPHA, PROJECT_ALPHA)
    _record_exit(seat_db, surface="codex-cli")
    message = send_message(
        seat_db,
        actor_id=HUMAN_ACTOR_ID,
        sender_session_id=SESSION_BETA,
        selector=RecipientSelector(session_ids=[SESSION_ALPHA]),
        body="Continue steering",
    )
    seat_db.execute(
        "INSERT INTO session_message_attempts "
        "(attempt_id,message_id,target_session_id,attempt_kind,started_at) "
        "VALUES (%s,%s,%s,'wake_relay',%s)",
        (
            "resume-holder",
            message["message_id"],
            SESSION_ALPHA,
            instant_parameter(seat_db, utc_now()),
        ),
    )
    seat_db.commit()
    with pytest.raises(SessionError, match="already held"):
        acquire_steering(seat_db, SESSION_BETA, PROJECT_ALPHA)


@pytest.mark.parametrize("other_exited", [False, True])
def test_every_overlapping_holder_is_checked_before_any_release(seat_db, other_exited):
    from yoke_core.domain.work_claim_targets import make_steering_target
    from yoke_core.domain.steering_claims import list_claims

    old = acquire_steering(seat_db, SESSION_ALPHA, PROJECT_ALPHA)
    clock = instant_parameter(seat_db, utc_now())
    # Reproduce pre-existing overlapping rows; normal acquire prevents these.
    extra = seat_db.execute(
        "INSERT INTO work_claims "
        "(session_id,target_kind,scope,claim_type,claimed_at,last_heartbeat) "
        "VALUES (%s,'steering',%s,'exclusive',%s,%s) RETURNING id",
        (
            SESSION_BETA,
            make_steering_target(PROJECT_ALPHA, NEAR_TERM_PLAN_SLUG).scope_json(),
            clock,
            clock,
        ),
    ).fetchone()[0]
    from yoke_core.domain.strategy_execution import acquire_session_doc_claim

    acquire_session_doc_claim(
        seat_db,
        project_id=PROJECT_ALPHA,
        slug=NEAR_TERM_PLAN_SLUG,
        session_id=SESSION_BETA,
        actor_id=HUMAN_ACTOR_ID,
        steering_claim_id=extra,
    )
    seat_db.execute(
        "UPDATE harness_sessions SET ended_at=%s WHERE session_id=%s",
        (clock, SESSION_ALPHA),
    )
    if other_exited:
        seat_db.execute(
            "UPDATE harness_sessions SET ended_at=%s WHERE session_id=%s",
            (clock, SESSION_BETA),
        )
    seat_db.commit()
    from runtime.api.domain.steering_claim_test_support import SESSION_GAMMA

    if other_exited:
        acquired = acquire_steering(seat_db, SESSION_GAMMA, PROJECT_ALPHA)
        assert (
            list_claims(seat_db, project_id=PROJECT_ALPHA, active_only=True)[0]["id"]
            == acquired["id"]
        )
        assert (
            len(list_claims(seat_db, project_id=PROJECT_ALPHA, active_only=True)) == 1
        )
    else:
        with pytest.raises(SessionError) as refusal:
            acquire_steering(seat_db, SESSION_GAMMA, PROJECT_ALPHA)
        assert SESSION_BETA in str(refusal.value)
        assert {
            r["id"]
            for r in list_claims(seat_db, project_id=PROJECT_ALPHA, active_only=True)
        } == {old["id"], extra}
