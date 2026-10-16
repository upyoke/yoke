"""Org termination, evidence and action authority retain exclusive ownership."""

from dataclasses import replace
import json

import pytest

from runtime.api.domain.test_session_org_messages import (
    org_world as org_world,
    send,
    relay,
)
from runtime.api.domain.test_org_scope_relay_wake_jobs import heartbeat
from runtime.api.domain.test_org_scope_relay_reports import NOW, MACHINE
from runtime.api.domain.test_session_action_dispatch_permission import _entry, _request
from yoke_core.domain import actor_permissions
from yoke_core.domain.session_action_authority import authorize_session_action
from yoke_core.domain.session_action_dispatch_permission import (
    session_action_dispatch_permission,
)
from yoke_core.domain.session_termination import terminate_session
from yoke_core.domain.session_termination_reap import (
    claim_termination_reap,
    report_termination_reap,
)
from yoke_core.domain.session_evidence_fetch import (
    request_evidence_fetch,
    read_evidence_fetch,
    evidence_fetch_result,
)
from yoke_core.domain.session_evidence_relay_job import (
    claim_evidence_fetch,
    report_evidence_fetch,
)
from yoke_core.domain.session_relay_types import SessionRelayError
from yoke_core.domain.work_claim_targets import make_steering_target


@pytest.fixture
def world(org_world, monkeypatch):
    w = org_world
    target = make_steering_target(1)
    w.conn.execute(
        "INSERT INTO work_claims(session_id,target_kind,scope,claimed_at,last_heartbeat) "
        "VALUES ('project-sender',%s,%s,%s,%s)",
        (target.kind, target.scope_json(), NOW, NOW),
    )
    w.conn.commit()
    monkeypatch.setattr("yoke_core.domain.session_termination.utc_now", lambda: NOW)
    monkeypatch.setattr(
        "yoke_core.domain.session_termination.emit_session_terminated",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "yoke_core.domain.sessions_render_end._sa._emit_session_event",
        lambda *a, **k: None,
    )
    return w


def terminate(w, sid="org-target"):
    return terminate_session(
        w.conn,
        target_session_id=sid,
        actor_id=w.owner,
        caller_session_id="project-sender",
        reason="finished",
    )


def fetch(w, actor=None, sid="org-target"):
    return request_evidence_fetch(
        w.conn,
        actor_id=w.owner if actor is None else actor,
        caller_session_id="org-sender",
        session_id=sid,
        kind="watcher",
        file_name=None,
        evidence_id=None,
        tail_lines=20,
        now=NOW,
    )


def test_terminate_projectless_queues_org_reap_and_closes_receipts(world):
    w = world
    mid = send(w)["message_id"]
    w.conn.execute(
        "INSERT INTO session_message_attempts(attempt_id,message_id,target_session_id,attempt_kind,started_at) "
        "VALUES ('open',%s,'org-target','hook',%s)",
        (mid, NOW),
    )
    result = terminate(w)
    assert (
        result["reap_state"] == "pending" and result["cancelled_recipient_count"] == 1
    )
    row = w.conn.execute(
        "SELECT project_id,org_id,state FROM session_termination_reaps"
    ).fetchone()
    assert tuple(row) == (None, w.org, "pending")
    assert (
        w.conn.execute("SELECT state FROM session_message_recipients").fetchone()[0]
        == "cancelled"
    )
    attempt = w.conn.execute(
        "SELECT completed_at,result_code FROM session_message_attempts"
    ).fetchone()
    assert attempt[0] is not None and attempt[1] == "session_terminated"
    assert terminate(w)["deduplicated"]


@pytest.mark.parametrize(
    "actor,machine,projects,allowed",
    [
        ("owner", MACHINE, (), True),
        ("owner", MACHINE, (1,), True),
        ("reader", MACHINE, (), False),
        (None, MACHINE, (), False),
        ("owner", "remote-machine", (), False),
    ],
)
def test_org_reap_claimed_by_owner_relay_only(world, actor, machine, projects, allowed):
    w = world
    terminate(w)
    hb = replace(
        heartbeat(w, projects),
        actor_id=getattr(w, actor) if actor else None,
        machine_id=machine,
    )
    job = claim_termination_reap(w.conn, hb, now=NOW)
    assert (job is not None) == allowed
    assert w.conn.execute("SELECT state FROM session_termination_reaps").fetchone()[
        0
    ] == ("leased" if allowed else "pending")
    if job:
        assert job.project_id is None and job.target_workspace == "/tmp/message-fixture"
        assert job.to_dict()["project_id"] is None


def test_org_reap_job_completes_on_owner_relay(world):
    w = world
    relay(w)
    terminate(w)
    job = claim_termination_reap(w.conn, heartbeat(w), now=NOW)
    result = report_termination_reap(
        w.conn,
        relay_id="org-relay",
        target_session_id="org-target",
        lease_id=job.lease_id,
        result_code="terminated",
        adapter_revision="test",
        evidence={"process_gone": True},
        now=NOW,
    )
    assert result["result_code"] == "terminated"
    row = w.conn.execute(
        "SELECT state,completed_at FROM session_termination_reaps"
    ).fetchone()
    assert row[0] == "succeeded" and row[1] is not None


@pytest.mark.parametrize("workspace", ["", "   "])
def test_org_reap_missing_workspace_unavailable(world, workspace):
    w = world
    terminate(w)
    w.conn.execute(
        "UPDATE harness_sessions SET workspace=%s WHERE session_id='org-target'",
        (workspace,),
    )
    w.conn.commit()
    assert claim_termination_reap(w.conn, heartbeat(w), now=NOW) is None
    row = w.conn.execute(
        "SELECT state,result_code,evidence,lease_id FROM session_termination_reaps"
    ).fetchone()
    assert (
        row[0] == "unavailable"
        and row[1] == "session_workspace_unrecorded"
        and row[3] is None
    )
    assert json.loads(row[2])["result_code"] == "session_workspace_unrecorded"


@pytest.mark.parametrize("actor", ["owner", "operator"])
def test_evidence_fetch_org_actor_and_operator_allowed(world, actor):
    w = world
    record = fetch(w, getattr(w, actor))
    assert record["project_id"] is None and record["org_id"] == w.org
    again = fetch(w, getattr(w, actor))
    assert again["fetch_id"] == record["fetch_id"]


def test_evidence_fetch_org_stranger_refused_without_scope_disclosure(world):
    w = world
    w.conn.execute(
        "UPDATE harness_sessions SET workspace='/private/org-workspace',machine_id=NULL WHERE session_id='org-target'"
    )
    with pytest.raises(SessionRelayError) as exc:
        fetch(w, w.reader)
    assert exc.value.code == "permission_denied"
    assert "/private" not in str(exc.value) and "machine" not in str(exc.value)
    assert not w.conn.execute("SELECT 1 FROM session_evidence_fetches").fetchall()


@pytest.mark.parametrize(
    "actor,machine,allowed",
    [
        ("owner", MACHINE, True),
        ("reader", MACHINE, False),
        (None, MACHINE, False),
        ("owner", "remote-machine", False),
    ],
)
def test_org_evidence_leased_without_projects_by_own_relay_only(
    world, actor, machine, allowed
):
    w = world
    fetch(w)
    job = claim_evidence_fetch(
        w.conn,
        replace(
            heartbeat(w),
            actor_id=getattr(w, actor) if actor else None,
            machine_id=machine,
        ),
        now=NOW,
    )
    assert (job is not None) == allowed
    if job:
        assert job.project_id is None and job.target_workspace == "/tmp/message-fixture"
        assert job.evidence_request["tail_lines"] == 20


def test_org_evidence_report_completes_fetch(world):
    w = world
    relay(w)
    record = fetch(w)
    job = claim_evidence_fetch(w.conn, heartbeat(w), now=NOW)
    report_evidence_fetch(
        w.conn,
        relay_id="org-relay",
        fetch_id=job.job_id,
        lease_id=job.lease_id,
        result_code="read",
        document={"content": "safe tail"},
        now=NOW,
    )
    result = evidence_fetch_result(read_evidence_fetch(w.conn, record["fetch_id"]))
    assert result["state"] == "succeeded" and result["content"] == "safe tail"


def test_org_evidence_missing_workspace_is_terminal_without_job(world):
    w = world
    record = fetch(w)
    w.conn.execute(
        "UPDATE harness_sessions SET workspace='' WHERE session_id='org-target'"
    )
    w.conn.commit()
    assert claim_evidence_fetch(w.conn, heartbeat(w), now=NOW) is None
    record = read_evidence_fetch(w.conn, record["fetch_id"])
    assert (
        record["state"] == "failed"
        and record["result_code"] == "session_workspace_unrecorded"
    )
    assert record["lease_id"] is None and record["completed_at"] is not None
    assert evidence_fetch_result(record)["recovery"] == (
        "org-scoped session has no recorded workspace on this machine — terminate it deliberately "
        "(confirm the command with `yoke sessions --help`) or start a new session; project registration does not apply"
    )


@pytest.mark.parametrize(
    "function",
    [
        "session_control.session.wake",
        "session_control.keepalive.hold",
        "session_control.keepalive.release",
        "session_control.session.terminate",
    ],
)
@pytest.mark.parametrize(
    "actor,allowed",
    [("owner", True), ("operator", True), ("reader", False), ("admin", True)],
)
def test_session_action_org_target_authorization(world, function, actor, allowed):
    w = world
    actor_id = getattr(w, "operator" if actor == "admin" else actor)
    if actor == "admin":
        actor_permissions.grant_actor_org_role(
            w.conn,
            actor_id=actor_id,
            org_id=w.org,
            role_name="admin",
        )
    if function == "session_control.session.terminate" and actor == "operator":
        allowed = False
    target = dict(
        w.conn.execute(
            "SELECT * FROM harness_sessions WHERE session_id='org-target'"
        ).fetchone()
    )
    decision = authorize_session_action(
        w.conn,
        actor_id=actor_id,
        function_id=function,
        project_id=None,
        target=target,
    )
    assert decision.allowed == allowed and decision.project_id is None
    dispatch = session_action_dispatch_permission(
        w.conn,
        _entry(function),
        _request(function, {"session_id": "org-target"}),
        actor_id,
        None,
    )
    assert (dispatch.error is None) == allowed and dispatch.project_id is None
    if not allowed:
        assert (
            "project id" not in decision.message and "/private" not in decision.message
        )


def test_own_org_actor_needs_no_additional_membership(world):
    w = world
    w.conn.execute("DELETE FROM actor_org_roles WHERE actor_id=%s", (w.owner,))
    assert fetch(w)["org_id"] == w.org


def test_project_termination_and_evidence_unchanged(world):
    w = world
    terminate(w, "project-target")
    row = w.conn.execute(
        "SELECT project_id,org_id FROM session_termination_reaps"
    ).fetchone()
    assert tuple(row) == (1, None)
    assert claim_termination_reap(w.conn, heartbeat(w), now=NOW) is None
    assert claim_termination_reap(w.conn, heartbeat(w, (1,)), now=NOW).project_id == 1
    fetch(w, sid="project-sender")
    assert claim_evidence_fetch(w.conn, heartbeat(w), now=NOW) is None
    assert claim_evidence_fetch(w.conn, heartbeat(w, (1,)), now=NOW).project_id == 1
