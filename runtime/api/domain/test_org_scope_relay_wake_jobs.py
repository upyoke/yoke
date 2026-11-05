"""Org wake transport uses the owning relay and a recorded workspace."""

from runtime.api.domain.org_scope_relay_wake_jobs_test_support import (
    enqueue as enqueue,
    heartbeat as heartbeat,
    reserve as reserve,
)


from dataclasses import replace
from datetime import timedelta

import pytest

from runtime.api.domain.session_org_messages_test_support import (
    org_world as org_world,
    relay,
)
from runtime.api.domain.org_scope_relay_reports_test_support import NOW, OLD, MACHINE
from yoke_core.domain.session_manual_wake import request_session_wake
from yoke_core.domain.session_relay_wake_claim import wake_candidates
from yoke_core.domain.session_relay_jobs import claim_wake_job
from yoke_core.domain.session_wake_drain_cadence import wake_work_pending
from yoke_core.domain.session_private_route_qualification import (
    qualification_for_message,
    PrivateRouteQualificationError,
)
from yoke_core.domain.session_message_types import SessionMessageError
from yoke_core.domain.session_wake_meter import meter_wall
from yoke_core.domain import session_wake_meter as meter
from yoke_core.domain import session_relay as relay_domain
from yoke_core.domain.session_recovery_facts import record_native_turn_end
from yoke_core.domain.session_vendor_error_resume import resume_vendor_error_sessions


@pytest.mark.parametrize(
    "actor,machine,allowed",
    [
        ("owner", MACHINE, True),
        ("reader", MACHINE, False),
        (None, MACHINE, False),
        ("owner", "another-machine", False),
    ],
)
def test_org_wake_claimed_by_own_relay_only(org_world, actor, machine, allowed):
    w = org_world
    mid = enqueue(w)
    hb = replace(
        heartbeat(w), actor_id=getattr(w, actor) if actor else None, machine_id=machine
    )
    job = claim_wake_job(w.conn, hb, now=NOW)
    assert (job is not None) == allowed
    if job:
        assert job.message_id == mid
    else:
        assert not w.conn.execute("SELECT 1 FROM session_message_attempts").fetchall()


@pytest.mark.parametrize("projects", [(), (1,)])
def test_relay_without_projects_serves_own_org_rows(org_world, projects):
    w = org_world
    mid = enqueue(w)
    rows = wake_candidates(w.conn, heartbeat(w, projects), now=NOW)
    assert [(r["message_id"], r["session_id"]) for r in rows] == [(mid, "org-target")]
    assert rows[0]["actor_id"] == w.owner and rows[0]["org_id"] == w.org


def test_org_wake_job_carries_workspace_and_null_project(org_world):
    w = org_world
    mid = enqueue(w)
    job = claim_wake_job(w.conn, heartbeat(w), now=NOW)
    assert job and job.message_id == mid
    assert job.project_id is None and job.target_workspace == "/tmp/message-fixture"
    assert job.to_dict()["project_id"] is None
    assert "Please" not in job.native_instruction
    attempt = w.conn.execute(
        "SELECT completed_at FROM session_message_attempts"
    ).fetchone()
    assert attempt and attempt[0] is None


@pytest.mark.parametrize("workspace", ["", "   "])
def test_org_wake_without_workspace_not_issued(org_world, workspace):
    w = org_world
    enqueue(w)
    w.conn.execute(
        "UPDATE harness_sessions SET workspace=%s WHERE session_id='org-target'",
        (workspace,),
    )
    w.conn.commit()
    assert claim_wake_job(w.conn, heartbeat(w), now=NOW) is None
    row = w.conn.execute(
        "SELECT result_code,completed_at,evidence FROM session_message_attempts"
    ).fetchone()
    assert row[0] == "session_workspace_unrecorded" and row[1] is not None
    assert "workspace folder" in row[2]


@pytest.mark.parametrize(
    "actor,machine,projects,expected",
    [
        ("owner", MACHINE, (), True),
        ("reader", MACHINE, (), False),
        (None, MACHINE, (), False),
        ("owner", "another-machine", (), False),
        (None, MACHINE, (1,), False),
    ],
)
def test_wake_work_pending_sees_own_org_rows_only(
    org_world, actor, machine, projects, expected
):
    w = org_world
    enqueue(w)
    assert (
        wake_work_pending(
            w.conn,
            machine_id=machine,
            project_ids=projects,
            relay_actor_id=getattr(w, actor) if actor else None,
            now=NOW,
        )
        is expected
    )


def test_route_qualification_refuses_org_candidate(org_world):
    w = org_world
    with pytest.raises(PrivateRouteQualificationError) as exc:
        qualification_for_message(
            w.conn,
            {
                "project_id": None,
                "org_id": w.org,
                "executor_surface": "codex-cli",
                "executor_version": "0.1",
                "message_id": "unknown",
            },
            operation="resume",
            route="direct",
            now=NOW,
        )
    assert exc.value.code == "route_qualification_requires_project"
    assert "message a session started in that project's folder" in str(exc.value)


@pytest.mark.parametrize("actor", ["owner", "reader", None])
def test_broker_adoption_org_owner_relay(org_world, actor):
    w = org_world
    lease = reserve(w)
    hb = replace(heartbeat(w), actor_id=getattr(w, actor) if actor else None)
    job = claim_wake_job(
        w.conn,
        hb,
        now=NOW + timedelta(seconds=1),
        broker_only=True,
        broker_lease_id=lease.lease_id,
        broker_session_id="project-sender",
    )
    assert (job is not None) == (actor == "owner")
    if job:
        assert job.job_id == lease.attempt_id and job.project_id is None
        assert (
            job.target_workspace == "/tmp/message-fixture"
            and job.wake_route == "broker"
        )
    row = w.conn.execute("SELECT result_code FROM session_message_attempts").fetchone()
    assert row[0] == ("broker_native_claimed" if job else "broker_instructed")


def test_broker_org_without_workspace_closes_reservation(org_world):
    w = org_world
    lease = reserve(w)
    w.conn.execute(
        "UPDATE harness_sessions SET workspace='' WHERE session_id='org-target'"
    )
    w.conn.commit()
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
    row = w.conn.execute(
        "SELECT result_code,completed_at FROM session_message_attempts"
    ).fetchone()
    assert row[0] == "session_workspace_unrecorded" and row[1] is not None


def test_wake_meter_org_limits_or_named_refusal(org_world, monkeypatch):
    w = org_world
    w.conn.execute(
        "UPDATE harness_sessions SET model='gpt-5.4' WHERE session_id='org-target'"
    )

    def forbidden(*args, **kwargs):
        pytest.fail("Org meter must not call the project-only limits API")

    monkeypatch.setattr(meter, "load_plan_limits", forbidden)
    with pytest.raises(SessionMessageError) as exc:
        meter_wall(w.conn, "org-target", NOW)
    assert exc.value.code == "wake_meter_org_limits_unavailable"
    assert "Recovery:" in str(exc.value) and "project folder" in str(exc.value)


def test_vendor_resume_reaches_org_relay_job(org_world):
    w = org_world
    relay(w)
    record_native_turn_end(
        w.conn,
        "org-target",
        observation={
            "observed_at": (OLD + timedelta(minutes=1)).isoformat(),
            "error_message": "unexpected status 404 Not Found",
            "codex_error_info": "other",
        },
        recorded_at=OLD + timedelta(minutes=1),
    )
    w.conn.commit()
    result = resume_vendor_error_sessions(
        w.conn, machine_id=MACHINE, authorized_projects=[], actor_id=w.owner, now=NOW
    )
    assert result["resumed"] == ["org-target"] and not result["refused"]
    job = claim_wake_job(w.conn, heartbeat(w), now=NOW)
    assert job and job.target_session_id == "org-target" and job.project_id is None
    assert job.target_workspace == "/tmp/message-fixture"
    assert (
        w.conn.execute(
            "SELECT vendor_resume_attempts FROM harness_sessions WHERE session_id='org-target'"
        ).fetchone()[0]
        == 1
    )


def test_poll_threads_authenticated_actor_to_pending_scope(org_world, monkeypatch):
    w = org_world
    seen = []

    def pending(conn, **kwargs):
        seen.append(kwargs)
        return True

    monkeypatch.setattr(relay_domain, "wake_work_pending", pending)
    hb = replace(heartbeat(w), machine_id="11111111-1111-4111-8111-111111111111")
    outcome = relay_domain.claim_relay_job(
        w.conn, hb, wait_seconds=0, now_provider=lambda: NOW
    )
    assert not outcome.jobs and outcome.next_poll_seconds == 1
    assert seen == [
        {
            "machine_id": hb.machine_id,
            "project_ids": (),
            "relay_actor_id": w.owner,
            "now": NOW,
        }
    ]


def test_pinned_org_meter_does_not_abort_project_wake_collection(org_world):
    w = org_world
    enqueue(w)
    project_mid = request_session_wake(
        w.conn,
        actor_id=w.owner,
        caller_session_id="org-sender",
        session_id="project-target",
        public_ref=None,
        prompt=None,
        now=NOW,
    )["message_id"]
    w.conn.execute(
        "UPDATE harness_sessions SET model='gpt-5.4' WHERE session_id='org-target'"
    )
    w.conn.commit()
    rows = wake_candidates(w.conn, heartbeat(w, (1,)), now=NOW)
    assert [(row["message_id"], row["session_id"]) for row in rows] == [
        (project_mid, "project-target")
    ]
