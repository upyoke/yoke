"""A refused org meter cannot stop another recipient's wake or projection."""

from dataclasses import replace
from datetime import timedelta
import json

import pytest

from runtime.api.domain.test_session_org_messages import org_world as org_world
from runtime.api.domain.test_org_scope_relay_wake_jobs import (
    enqueue,
    heartbeat,
    reserve,
)
from runtime.api.domain.test_org_scope_relay_reports import NOW, OLD, MACHINE
from yoke_contracts.session_control.models import RecipientSelector
from yoke_core.domain.session_broker_wake import lease_broker_wake_for_hook
from yoke_core.domain.session_broker_wake_settlement import complete_broker_hook_lease
from yoke_core.domain.session_message_service import send_message
from yoke_core.domain.session_manual_wake import request_session_wake
from yoke_core.domain.session_message_types import SessionMessageError
from yoke_core.domain.session_relay import claim_relay_job
from yoke_core.domain.session_relay_jobs import claim_wake_job
from yoke_core.domain.session_relay_wake_claim import (
    wake_candidates,
    claim_wake_attempt,
)
from yoke_core.domain.session_wake_meter import (
    overlay_resume_state,
    refuse_exhausted_wake,
    skip_exhausted_wake,
)

CODE = "wake_meter_org_limits_unavailable"
HOST = "11111111-1111-4111-8111-111111111111"


def pin(w):
    w.conn.execute(
        "UPDATE harness_sessions SET model='gpt-5.4' WHERE session_id='org-target'"
    )
    w.conn.commit()


def refusal_rows(w):
    return w.conn.execute(
        "SELECT target_session_id,completed_at,evidence FROM session_message_attempts WHERE result_code=%s",
        (CODE,),
    ).fetchall()


def mixed(w):
    enqueue(w)
    mid = request_session_wake(
        w.conn,
        actor_id=w.owner,
        caller_session_id="org-sender",
        session_id="project-target",
        public_ref=None,
        prompt=None,
        now=NOW,
    )["message_id"]
    pin(w)
    return mid


@pytest.mark.parametrize("actor", ["owner", "reader"])
def test_mixed_project_poll_survives_refused_org_meter(org_world, actor):
    w = org_world
    mid = mixed(w)
    for table in ("harness_sessions", "session_message_recipients", "session_relays"):
        w.conn.execute(
            f"UPDATE {table} SET machine_id=%s WHERE machine_id=%s", (HOST, MACHINE)
        )
    w.conn.commit()
    hb = replace(
        heartbeat(w, (1,)),
        actor_id=getattr(w, actor),
        machine_id=HOST,
        relay_id=f"project-relay-{actor}",
    )
    result = claim_relay_job(w.conn, hb, wait_seconds=0, now_provider=lambda: NOW)
    assert [job.message_id for job in result.jobs] == [mid]
    assert result.jobs[0].project_id == 1
    rows = refusal_rows(w)
    assert len(rows) == 1 and rows[0][0] == "org-target" and rows[0][1] is not None


@pytest.mark.parametrize(
    "actor,machine", [("reader", MACHINE), ("owner", "remote"), (None, MACHINE)]
)
def test_foreign_relay_collection_does_not_raise_or_issue_org_job(
    org_world, actor, machine
):
    w = org_world
    enqueue(w)
    pin(w)
    hb = replace(
        heartbeat(w), actor_id=getattr(w, actor) if actor else None, machine_id=machine
    )
    assert claim_wake_job(w.conn, hb, now=NOW) is None
    assert not w.conn.execute(
        "SELECT 1 FROM session_message_attempts WHERE completed_at IS NULL"
    ).fetchall()


def test_own_org_meter_refusal_is_recorded_once_without_dispatch(org_world):
    w = org_world
    enqueue(w)
    pin(w)
    for _ in range(2):
        assert claim_wake_job(w.conn, heartbeat(w), now=NOW) is None
    rows = refusal_rows(w)
    assert len(rows) == 1 and rows[0][0] == "org-target" and rows[0][1] is not None
    evidence = json.loads(rows[0][2])
    assert evidence["result_code"] == CODE and evidence["skip_reason"] == CODE
    assert "Recovery:" in evidence["probe_detail"]
    assert not w.conn.execute(
        "SELECT 1 FROM session_message_attempts WHERE completed_at IS NULL"
    ).fetchall()


def test_atomic_claim_rechecks_new_org_meter_refusal(org_world):
    w = org_world
    enqueue(w)
    (candidate,) = wake_candidates(w.conn, heartbeat(w), now=NOW)
    pin(w)
    assert claim_wake_attempt(w.conn, candidate=candidate, now=NOW) is None
    assert len(refusal_rows(w)) == 1


def test_manual_wake_keeps_named_refusal_without_new_envelope(org_world):
    w = org_world
    enqueue(w)
    pin(w)
    refusal = refuse_exhausted_wake(w.conn, "org-target", NOW)
    assert isinstance(refusal, SessionMessageError) and refusal.code == CODE
    count = w.conn.execute("SELECT count(*) FROM session_messages").fetchone()[0]
    with pytest.raises(SessionMessageError) as exc:
        request_session_wake(
            w.conn,
            actor_id=w.owner,
            caller_session_id="org-sender",
            session_id="org-target",
            public_ref=None,
            prompt=None,
            now=NOW,
        )
    assert exc.value.code == CODE
    assert (
        w.conn.execute("SELECT count(*) FROM session_messages").fetchone()[0] == count
    )


@pytest.mark.parametrize(
    "state,expected",
    [
        ("resumed-died", "blocked-org-limits-unavailable"),
        ("queued", "queued"),
        (None, None),
    ],
)
def test_org_resume_projection_is_scoped_and_nonthrowing(org_world, state, expected):
    w = org_world
    pin(w)
    assert overlay_resume_state(w.conn, "org-target", state, now=NOW) == expected
    assert (
        overlay_resume_state(w.conn, "project-target", "resumed-died", now=NOW)
        == "resumed-died"
    )


def test_broker_adoption_records_own_org_meter_refusal(org_world):
    w = org_world
    lease = reserve(w)
    pin(w)
    assert (
        claim_wake_job(
            w.conn,
            heartbeat(w),
            now=NOW,
            broker_only=True,
            broker_lease_id=lease.lease_id,
            broker_session_id="project-sender",
        )
        is None
    )
    assert len(refusal_rows(w)) == 1
    assert not w.conn.execute(
        "SELECT 1 FROM session_message_attempts WHERE completed_at IS NULL"
    ).fetchall()


def test_project_broker_adopts_despite_another_org_meter_refusal(org_world):
    w = org_world
    enqueue(w)
    w.conn.execute(
        "UPDATE harness_sessions SET turn_posture='waiting' WHERE session_id='project-target'"
    )
    send_message(
        w.conn,
        actor_id=w.owner,
        sender_session_id="org-sender",
        selector=RecipientSelector(session_ids=["project-target"]),
        body="Report the result.",
        now=NOW - timedelta(minutes=11),
    )
    pin(w)
    w.conn.execute(
        "UPDATE session_relays SET connected_until=%s,project_checkouts='[1]'", (OLD,)
    )
    w.conn.commit()
    lease = lease_broker_wake_for_hook(
        w.conn, broker_session_id="project-sender", hook_event="PreToolUse", now=NOW
    )
    assert lease
    complete_broker_hook_lease(
        w.conn, lease_id=lease.lease_id, delivered=True, result="injected", now=NOW
    )
    w.conn.execute(
        "UPDATE session_relays SET connected_until=%s", (NOW + timedelta(hours=1),)
    )
    w.conn.commit()
    job = claim_wake_job(
        w.conn,
        heartbeat(w, (1,)),
        now=NOW,
        broker_only=True,
        broker_lease_id=lease.lease_id,
        broker_session_id="project-sender",
    )
    assert job and job.target_session_id == "project-target" and job.project_id == 1
    assert len(refusal_rows(w)) == 1


def test_unrelated_meter_errors_are_not_silently_skipped(org_world, monkeypatch):
    def broken(*args, **kwargs):
        raise SessionMessageError("unrelated_failure", "unrelated failure")

    monkeypatch.setattr("yoke_core.domain.session_wake_meter.meter_wall", broken)
    with pytest.raises(SessionMessageError) as exc:
        skip_exhausted_wake(org_world.conn, {"session_id": "org-target"}, NOW)
    assert exc.value.code == "unrelated_failure"
