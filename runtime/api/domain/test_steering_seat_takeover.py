"""Terminal facts and explicit intent govern steering-seat takeover."""

from datetime import timedelta
import json

import pytest

from runtime.api.domain.steering_claim_test_support import (
    HUMAN_ACTOR_ID,
    PROJECT_ALPHA,
    SESSION_ALPHA,
    SESSION_BETA,
    SESSION_GAMMA,
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
from yoke_core.domain.steering_claims import acquire, list_claims
from yoke_core.domain.strategy_docs_defaults import NEAR_TERM_PLAN_SLUG
from yoke_core.domain.strategy_doc_steering_pair import active_paired_session_doc_claim


@pytest.fixture
def seat_db(test_db):
    seed_standard_steering_world(test_db)
    seed_roles_and_permissions(test_db)
    grant_actor_project_role(
        test_db, actor_id=HUMAN_ACTOR_ID, project_id=PROJECT_ALPHA,
        role_name=ROLE_OPERATOR,
    )
    test_db.execute(
        "UPDATE harness_sessions SET executor_surface='codex-cli', "
        "executor_version='0.161.0'"
    )
    test_db.commit()
    return test_db


def _take(conn, *, session_id=SESSION_BETA, reason="recover stuck steering", **kwargs):
    return acquire(
        conn, session_id=session_id, project_id=PROJECT_ALPHA,
        actor_id=HUMAN_ACTOR_ID, take_over=True, reason=reason, **kwargs,
    )


@pytest.mark.parametrize("stamp", [None, "ended_at", "terminated_at"])
@pytest.mark.parametrize("explicit", [False, True])
@pytest.mark.parametrize("document", [None, NEAR_TERM_PLAN_SLUG])
def test_terminal_or_explicit_takeover_releases_paired_lock(
    seat_db, stamp, explicit, document,
):
    scope = dict(document=document, plan_document=None if document else NEAR_TERM_PLAN_SLUG)
    old = acquire_steering(seat_db, SESSION_ALPHA, PROJECT_ALPHA, **scope)
    if stamp:
        seat_db.execute(
            f"UPDATE harness_sessions SET {stamp}=%s WHERE session_id=%s",
            (instant_parameter(seat_db, utc_now()), SESSION_ALPHA),
        )
        seat_db.commit()
    if not stamp and not explicit:
        with pytest.raises(SessionError) as refusal:
            acquire_steering(seat_db, SESSION_BETA, PROJECT_ALPHA, **scope)
        assert refusal.value.code == "ALREADY_CLAIMED"
        assert "--take-over --reason TEXT" in str(refusal.value)
        assert active_paired_session_doc_claim(seat_db, old["id"]) is not None
        return
    new = (_take(seat_db, **scope) if explicit else
           acquire_steering(seat_db, SESSION_BETA, PROJECT_ALPHA, **scope))
    assert new["session_id"] == SESSION_BETA
    assert new["document_claim"]["owner_session_id"] == SESSION_BETA
    assert active_paired_session_doc_claim(seat_db, old["id"]) is None
    released = seat_db.execute(
        "SELECT released_at, release_reason_intent FROM work_claims WHERE id=%s",
        (old["id"],),
    ).fetchone()
    assert released["released_at"] is not None
    if explicit:
        assert released["release_reason_intent"] == "recover stuck steering"
    else:
        assert f"taken over by session {SESSION_BETA}" in released["release_reason_intent"]
    notices = seat_db.execute("SELECT body FROM session_messages").fetchall()
    if stamp == "terminated_at":
        assert not notices
    else:
        assert len(notices) == 1
        assert SESSION_BETA in notices[0]["body"]
        assert "Reacquire" in notices[0]["body"]
        if explicit:
            assert "recover stuck steering" in notices[0]["body"]


@pytest.mark.parametrize("reason", [None, "", "   "])
def test_explicit_takeover_requires_reason_before_releasing(seat_db, reason):
    old = acquire_steering(seat_db, SESSION_ALPHA, PROJECT_ALPHA)
    with pytest.raises(SessionError, match="--take-over requires --reason") as refusal:
        _take(seat_db, reason=reason)
    assert refusal.value.code == "REASON_REQUIRED"
    assert list_claims(seat_db, active_only=True)[0]["id"] == old["id"]


SURFACES = [
    "claude-cli", "codex-cli", "cursor-cli",
    "claude-desktop", "codex-desktop", "cursor-desktop",
]


@pytest.mark.parametrize("surface", SURFACES)
@pytest.mark.parametrize("clean", [False, True])
def test_process_exit_alone_never_releases_holder(seat_db, surface, clean):
    old = acquire_steering(seat_db, SESSION_ALPHA, PROJECT_ALPHA)
    now = utc_now()
    seat_db.execute(
        "UPDATE harness_sessions SET executor_surface=%s, executor_version=%s, mode=%s, "
        "native_process_gone_at=%s, native_process_gone_evidence=%s, "
        "last_heartbeat=%s WHERE session_id=%s",
        (surface, capability_for_surface(surface).minimum_version,
         "parked" if clean else "wait", instant_parameter(seat_db, now),
         json.dumps({"exit_code": 0 if clean else 1}),
         instant_parameter(seat_db, now - timedelta(days=30)), SESSION_ALPHA),
    )
    seat_db.commit()
    with pytest.raises(SessionError, match="--take-over --reason TEXT"):
        acquire_steering(seat_db, SESSION_BETA, PROJECT_ALPHA)
    assert acquire_steering(seat_db, SESSION_ALPHA, PROJECT_ALPHA)["id"] == old["id"]


@pytest.mark.parametrize("surface", SURFACES)
def test_live_holder_receives_notice_on_every_surface(seat_db, surface):
    from yoke_core.domain.session_message_delivery import lease_for_hook

    seat_db.execute(
        "UPDATE harness_sessions SET executor_surface=%s, executor_version=%s "
        "WHERE session_id=%s",
        (surface, capability_for_surface(surface).minimum_version, SESSION_ALPHA),
    )
    seat_db.commit()
    acquire_steering(seat_db, SESSION_ALPHA, PROJECT_ALPHA)
    _take(seat_db)
    receipt = lease_for_hook(
        seat_db, session_id=SESSION_ALPHA,
        hook_event=capability_for_surface(surface).inject_events[0], limit=10,
    )
    assert receipt is not None
    assert len(receipt["messages"]) == 1
    assert "recover stuck steering" in receipt["messages"][0]["body"]


@pytest.mark.parametrize("other_ended", [False, True])
@pytest.mark.parametrize("explicit", [False, True])
def test_every_overlap_is_checked_before_any_release(seat_db, other_ended, explicit):
    from yoke_core.domain.work_claim_targets import make_steering_target
    from yoke_core.domain.strategy_execution import acquire_session_doc_claim

    old = acquire_steering(seat_db, SESSION_ALPHA, PROJECT_ALPHA)
    clock = instant_parameter(seat_db, utc_now())
    extra = seat_db.execute(
        "INSERT INTO work_claims "
        "(session_id,target_kind,scope,claim_type,claimed_at,last_heartbeat) "
        "VALUES (%s,'steering',%s,'exclusive',%s,%s) RETURNING id",
        (SESSION_BETA, make_steering_target(PROJECT_ALPHA, NEAR_TERM_PLAN_SLUG).scope_json(),
         clock, clock),
    ).fetchone()[0]
    acquire_session_doc_claim(
        seat_db, project_id=PROJECT_ALPHA, slug=NEAR_TERM_PLAN_SLUG,
        session_id=SESSION_BETA, actor_id=HUMAN_ACTOR_ID, steering_claim_id=extra,
    )
    seat_db.execute(
        "UPDATE harness_sessions SET ended_at=%s WHERE session_id=%s",
        (clock, SESSION_ALPHA),
    )
    if other_ended:
        seat_db.execute(
            "UPDATE harness_sessions SET ended_at=%s WHERE session_id=%s",
            (clock, SESSION_BETA),
        )
    seat_db.commit()
    if explicit or other_ended:
        new = (_take(seat_db, session_id=SESSION_GAMMA) if explicit else
               acquire_steering(seat_db, SESSION_GAMMA, PROJECT_ALPHA))
        assert [r["id"] for r in list_claims(seat_db, active_only=True)] == [new["id"]]
        assert active_paired_session_doc_claim(seat_db, extra) is None
    else:
        with pytest.raises(SessionError, match="--take-over --reason TEXT"):
            acquire_steering(seat_db, SESSION_GAMMA, PROJECT_ALPHA)
        assert {r["id"] for r in list_claims(seat_db, active_only=True)} == {old["id"], extra}
