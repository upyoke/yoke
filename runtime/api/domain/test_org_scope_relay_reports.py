"""Relay ownership isolates org reports, recovery and installed binary routes."""

from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

import pytest

from yoke_contracts.timestamps import format_instant
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.external_identities import default_org_id
from yoke_core.domain import session_native_turn_end as turns
from yoke_core.domain import session_process_liveness_report as liveness
from yoke_core.domain import session_idle_host_report as idle
from yoke_core.domain import session_vendor_error_resume as resume
from yoke_core.domain.session_capacity_recovery import relaunch_capacity_worker
from yoke_core.domain.session_relay_machine_versions import (
    connected_relay_routes,
    machine_surface_versions,
)
from yoke_core.domain.session_vendor_error_states import vendor_error_states
from yoke_core.domain.session_recovery_facts import (
    record_native_turn_end,
    resume_episode_key,
)
from yoke_core.domain.handlers.session_keepalive import _authorized_target
from yoke_core.domain.session_keepalive import hold_session_keepalive
from yoke_core.domain.session_message_types import SessionMessageError
from runtime.api.domain.test_session_process_liveness_report import MEASURED_USAGE

NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)
OLD = NOW - timedelta(hours=2)
MACHINE = "org-machine"


@pytest.fixture
def world(test_db):
    owner = seed_human_actor(test_db, "Session owner")
    foreign = seed_human_actor(test_db, "Foreign owner")
    org = default_org_id(test_db)
    for sid, actor, machine, project in (
        ("own", owner, MACHINE, None),
        ("foreign", foreign, MACHINE, None),
        ("remote", owner, "other-machine", None),
        ("project", foreign, MACHINE, 1),
    ):
        test_db.execute(
            "INSERT INTO harness_sessions (session_id,executor,executor_surface,provider,"
            "workspace,project_id,org_id,actor_id,machine_id,offered_at,last_heartbeat,"
            "last_tool_call_at,turn_posture) VALUES (%s,'codex','codex-cli','openai',"
            "'/tmp/relay-fixture',%s,%s,%s,%s,%s,%s,%s,'running')",
            (sid, project, None if project else org, actor, machine, OLD, OLD, OLD),
        )
    test_db.commit()
    return test_db, owner, foreign


def _expected(actor, owner, foreign):
    return ["project"] + (
        ["own"] if actor == owner else ["foreign"] if actor == foreign else []
    )


@pytest.mark.parametrize("relay", ["owner", "foreign", None])
def test_turn_end_org_session_requires_own_relay_actor(world, relay):
    conn, owner, foreign = world
    actor = owner if relay == "owner" else foreign if relay == "foreign" else None
    result = turns.apply_native_turn_ends(
        conn,
        machine_id=MACHINE,
        authorized_projects=[1],
        relay_actor_id=actor,
        reports=[
            {"session_id": sid, "observed_at": format_instant(NOW)}
            for sid in ("own", "foreign", "remote", "project")
        ],
        now=NOW,
    )
    assert set(result["reclassified"]) == set(_expected(actor, owner, foreign))
    assert {row["session_id"]: row["status"] for row in result["skipped"]}[
        "remote"
    ] == "machine_mismatch"
    assert conn.execute(
        "SELECT native_turn_end_observation FROM harness_sessions WHERE session_id='project'"
    ).fetchone()[0]


@pytest.mark.parametrize("relay", ["owner", "foreign", None])
def test_native_turn_probe_org_and_project_ownership(world, relay):
    conn, owner, foreign = world
    for sid in ("own", "foreign", "remote", "project"):
        conn.execute(
            "INSERT INTO work_claims(session_id,target_kind,scope,claimed_at,last_heartbeat) "
            "VALUES (%s,'process','{}',%s,%s)",
            (sid, OLD, OLD),
        )
    actor = owner if relay == "owner" else foreign if relay == "foreign" else None
    targets = turns.probe_targets(
        conn, machine_id=MACHINE, authorized_projects=[1], relay_actor_id=actor, now=NOW
    )
    assert {row["session_id"] for row in targets} == set(
        _expected(actor, owner, foreign)
    )
    assert (
        turns.probe_targets(
            conn, machine_id="", authorized_projects=[], relay_actor_id=owner
        )
        == []
    )
    assert turns.probe_targets(conn, machine_id=MACHINE, authorized_projects=[]) == []
    assert [
        r["session_id"]
        for r in turns.probe_targets(
            conn, machine_id=MACHINE, authorized_projects=[], relay_actor_id=owner
        )
    ] == ["own"]


def test_native_turn_probe_refused_wake_org_session(world):
    conn, owner, _ = world
    conn.execute(
        "INSERT INTO session_messages(message_id,sender_actor_id,body,body_sha256,selector_snapshot,created_at,expires_at) "
        "VALUES ('refused-message',%s,'resume','sha','{}',%s,%s)",
        (owner, OLD, NOW + timedelta(hours=1)),
    )
    for sid in ("own", "foreign", "remote"):
        conn.execute(
            "INSERT INTO session_message_recipients(message_id,session_id,org_id,state,resolution_evidence,routing_snapshot,wake_after,created_at) "
            "VALUES ('refused-message',%s,%s,'pending','{}','{}',%s,%s)",
            (sid, default_org_id(conn), OLD, OLD),
        )
        conn.execute(
            "INSERT INTO session_message_attempts(attempt_id,message_id,target_session_id,attempt_kind,started_at,result_code) "
            "VALUES (%s,'refused-message',%s,'wake_relay',%s,'skipped_operation')",
            (sid, sid, OLD),
        )
    result = turns.probe_targets(
        conn, machine_id=MACHINE, authorized_projects=[], relay_actor_id=owner, now=NOW
    )
    assert [row["session_id"] for row in result] == ["own"]


@pytest.mark.parametrize("relay", ["owner", "foreign", None])
def test_liveness_org_session_usage_and_foreign_relay_refusal(
    world, monkeypatch, relay
):
    conn, owner, foreign = world
    actor = owner if relay == "owner" else foreign if relay == "foreign" else None
    reconciled = []
    monkeypatch.setattr(
        liveness,
        "settle_and_notify_native_death",
        lambda c, sid, e: reconciled.append(sid),
    )
    monkeypatch.setattr(
        liveness,
        "session_holdings_by_session",
        lambda *a, **k: {
            sid: {"current": ["held"]} for sid in ("own", "foreign", "project")
        },
    )
    result = liveness.apply_verified_process_death_reports(
        conn,
        machine_id=MACHINE,
        authorized_projects=[1],
        relay_actor_id=actor,
        reports=[
            {"session_id": sid, "usage_totals": MEASURED_USAGE}
            for sid in ("own", "foreign", "remote", "project")
        ],
        now=NOW,
    )
    allowed = set(_expected(actor, owner, foreign))
    assert set(reconciled) == allowed
    statuses = {row["session_id"]: row["status"] for row in result["skipped"]}
    assert statuses["remote"] == "machine_mismatch"
    for sid in ("own", "foreign", "project"):
        row = conn.execute(
            "SELECT usage_totals,native_process_gone_at FROM harness_sessions WHERE session_id=%s",
            (sid,),
        ).fetchone()
        if sid in allowed:
            assert json.loads(row[0])["models"] == json.loads(MEASURED_USAGE)["models"]
            assert row[1] is not None and statuses[sid] == "claims_held"
        else:
            assert row[0] is None and row[1] is None
            assert statuses[sid] == "project_unauthorized"


@pytest.mark.parametrize("actor_present", [False, True])
def test_idle_host_org_session_own_relay_actor(world, actor_present):
    conn, owner, _ = world
    conn.execute("UPDATE harness_sessions SET ended_at=%s", (NOW,))
    result = idle.apply_idle_host_report(
        conn,
        machine_id=MACHINE,
        authorized_projects=[1],
        relay_actor_id=owner if actor_present else None,
        hosts=[{"session_id": sid} for sid in ("own", "foreign", "remote", "project")],
        reclaimed=[{"session_id": "own", "pid": 42}],
    )
    assert set(result["ended"]) == (
        {"own", "project"} if actor_present else {"project"}
    )
    assert result["recorded"] == (["own"] if actor_present else [])
    assert {r["session_id"]: r["status"] for r in result["skipped"]}[
        "foreign"
    ] == "project_unauthorized"


def test_keepalive_org_session_owner(world):
    conn, owner, foreign = world
    request = SimpleNamespace(actor=SimpleNamespace(actor_id=owner))
    assert _authorized_target(conn, request, "own")["actor_id"] == owner
    held = hold_session_keepalive(conn, "own", seconds=60, reason="in progress")
    assert held["keepalive_until"]
    request.actor.actor_id = foreign
    with pytest.raises(SessionMessageError, match="authorized connection"):
        _authorized_target(conn, request, "own")


def _observe_all(conn):
    for sid in ("own", "foreign", "remote", "project"):
        record_native_turn_end(
            conn,
            sid,
            observation={
                "observed_at": format_instant(OLD + timedelta(minutes=1)),
                "error_message": "unexpected status 404 Not Found",
                "codex_error_info": "other",
            },
            recorded_at=OLD + timedelta(minutes=1),
        )
    conn.commit()


@pytest.mark.parametrize("relay", ["owner", "foreign", None])
def test_vendor_error_states_relay_actor_or_project_only(world, relay):
    conn, owner, foreign = world
    _observe_all(conn)
    actor = owner if relay == "owner" else foreign if relay == "foreign" else None
    states = vendor_error_states(
        conn, machine_id=MACHINE, authorized_projects=[1], relay_actor_id=actor, now=NOW
    )
    assert {s["session_id"] for s in states} == set(_expected(actor, owner, foreign))
    org_states = vendor_error_states(
        conn, machine_id=MACHINE, authorized_projects=[], relay_actor_id=owner, now=NOW
    )
    assert [s["session_id"] for s in org_states] == ["own"]
    assert org_states[0]["org_id"] == default_org_id(conn)
    assert vendor_error_states(conn, authorized_projects=[], now=NOW) == []
    assert (
        vendor_error_states(conn, authorized_projects=[], relay_actor_id=owner, now=NOW)
        == []
    )


def test_vendor_error_resume_org_session_own_relay(world, monkeypatch):
    conn, owner, _ = world
    _observe_all(conn)
    wakes = []
    monkeypatch.setattr(
        "yoke_core.domain.session_manual_wake.request_session_wake",
        lambda c, **kw: wakes.append(kw["session_id"]) or {"message_id": "wake"},
    )
    result = resume.resume_vendor_error_sessions(
        conn, machine_id=MACHINE, authorized_projects=[], actor_id=owner, now=NOW
    )
    assert result["resumed"] == wakes == ["own"]
    assert (
        conn.execute(
            "SELECT vendor_resume_attempts FROM harness_sessions WHERE session_id='foreign'"
        ).fetchone()[0]
        == 0
    )


def test_capacity_recovery_org_session_named_refusal(world):
    conn, owner, _ = world
    state = dict(
        conn.execute("SELECT * FROM harness_sessions WHERE session_id='own'").fetchone()
    )
    state.update(episode_key=resume_episode_key(OLD), actor_id=owner)
    result = relaunch_capacity_worker(conn, state=state, now=NOW)
    assert result["code"] == "capacity_recovery_project_required"
    assert "open a session in the project folder" in result["detail"]
    assert (
        "capacity_recovery_project_required"
        in conn.execute(
            "SELECT native_turn_end_observation FROM harness_sessions WHERE session_id='own'"
        ).fetchone()[0]
    )


def test_org_session_peer_binary_wake_fallback(world):
    conn, owner, foreign = world
    for relay_id, actor, machine, version in (
        ("own", owner, MACHINE, "2.0"),
        ("foreign", foreign, MACHINE, "3.0"),
        ("remote", owner, "other-machine", "4.0"),
    ):
        conn.execute(
            "INSERT INTO session_relays(relay_id,actor_id,machine_id,hostname,surface_versions,project_checkouts,first_seen_at,last_seen_at,connected_until,state) "
            "VALUES (%s,%s,%s,'host',%s,%s,%s,%s,%s,'active')",
            (
                relay_id,
                actor,
                machine,
                json.dumps({"codex-cli": version}),
                "[]" if relay_id == "own" else "[1]",
                OLD,
                NOW,
                NOW + timedelta(hours=1),
            ),
        )
    routes = connected_relay_routes(conn, now=NOW)
    assert machine_surface_versions(
        routes, machine_id=MACHINE, project_id=None, session_actor_id=owner
    ) == {"codex-cli": "2.0"}
    assert machine_surface_versions(routes, machine_id=MACHINE, project_id=None) == {}
    assert (
        machine_surface_versions(
            routes, machine_id="absent", project_id=None, session_actor_id=owner
        )
        == {}
    )
    assert machine_surface_versions(routes, machine_id=MACHINE, project_id=1) == {
        "codex-cli": "3.0"
    }
    assert (
        resume._installed_version(
            conn,
            {"project_id": None, "actor_id": owner, "executor_surface": "codex-cli"},
            machine_id=MACHINE,
            now=NOW,
        )
        == "2.0"
    )
