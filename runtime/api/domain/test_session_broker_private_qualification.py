"""Private direct grants keep broker selection from stealing the proof."""

from __future__ import annotations

from datetime import timedelta

from yoke_contracts.session_control.private_route_qualification import (
    QUALIFICATION_RELEASE_REASON,
    PrivateRouteQualificationScope,
)
from yoke_core.domain.actor_permissions import ROLE_ADMIN, grant_actor_project_role
from yoke_core.domain.session_broker_wake import lease_broker_wake_for_hook
from yoke_core.domain.session_broker_wake_settlement import complete_broker_hook_lease
from yoke_core.domain.session_private_route_qualification import (
    open_qualification_grant,
)
from yoke_core.domain.session_relay_storage import heartbeat_relay
from yoke_core.domain.session_relay import claim_relay_job
from yoke_core.domain.session_relay_types import RelayHeartbeat
from runtime.api.domain.test_session_broker_wake import MACHINE_ID, _seed
from runtime.api.domain.test_session_message_support import (
    NOW,
    NOW_TEXT,
    add_coordination_lease_schema,
)


RELEASE_SHA = "a" * 40


def _candidate_connection(monkeypatch, *, route: str):
    monkeypatch.setenv("YOKE_ENVIRONMENT", "stage")
    monkeypatch.setenv("YOKE_BUILD_SHA", RELEASE_SHA)
    conn, message_id = _seed()
    add_coordination_lease_schema(conn)
    conn.execute("ALTER TABLE harness_sessions ADD COLUMN actor_id INTEGER")
    conn.execute("ALTER TABLE harness_sessions ADD COLUMN mode TEXT")
    conn.execute(
        "UPDATE harness_sessions SET actor_id=10,mode='operator' WHERE session_id='s1'"
    )
    # Route-scoped grants only arbitrate where a grant is still required, so
    # the target is idle rather than ended: a stopped wake needs no grant now.
    # Day-old activity keeps it idle under any staleness window.
    idle_since = str(NOW - timedelta(days=1))
    conn.execute(
        "UPDATE harness_sessions SET executor='claude-code',"
        "executor_surface='claude-cli',executor_version='2.1.241',"
        "ended_at=NULL,last_heartbeat=?,last_tool_call_at=? "
        "WHERE session_id='s4'",
        (idle_since, idle_since),
    )
    conn.execute(
        "UPDATE session_message_recipients SET executor_surface='claude-cli',"
        "executor_version='2.1.241',machine_id=? WHERE message_id=?",
        (MACHINE_ID, message_id),
    )
    conn.execute(
        "UPDATE session_messages SET idempotency_key=? WHERE message_id=?",
        ("fleet-live:broker-route-proof:claude-cli:wake", message_id),
    )
    grant_actor_project_role(conn, actor_id=10, project_id=1, role_name=ROLE_ADMIN)
    conn.commit()
    grant = open_qualification_grant(
        conn,
        project_id=1,
        sender_session_id="s1",
        operator_actor_id=10,
        scope=PrivateRouteQualificationScope(
            release_sha=RELEASE_SHA,
            acceptance_run_id="broker-route-proof",
            surface="claude-cli",
            version="2.1.241",
            operation="message_idle",
            route=route,
        ),
    )
    heartbeat = RelayHeartbeat(
        relay_id=f"machine:{MACHINE_ID}",
        actor_id=10,
        machine_id=MACHINE_ID,
        hostname="qualification-relay",
        relay_version="0.1.1",
        surface_versions={"claude-cli": "2.1.241"},
        project_ids=(1,),
    )
    heartbeat_relay(
        conn,
        heartbeat,
        state="active",
        next_poll_seconds=30,
        now=NOW_TEXT,
    )
    return conn, grant, heartbeat


def test_exact_direct_grant_prevents_peer_broker_reservation(monkeypatch) -> None:
    conn, grant, _heartbeat = _candidate_connection(monkeypatch, route="direct")

    lease = lease_broker_wake_for_hook(
        conn,
        broker_session_id="broker-a",
        hook_event="PreToolUse",
        now=NOW + timedelta(seconds=1),
    )

    assert lease is None
    row = conn.execute(
        "SELECT released_at FROM coordination_leases WHERE id=?",
        (grant.lease_id,),
    ).fetchone()
    assert row["released_at"] is None
    assert (
        conn.execute("SELECT COUNT(*) FROM session_message_attempts").fetchone()[0] == 0
    )


def test_broker_scoped_grant_does_not_claim_direct_availability(monkeypatch) -> None:
    conn, grant, heartbeat = _candidate_connection(monkeypatch, route="broker")

    lease = lease_broker_wake_for_hook(
        conn,
        broker_session_id="broker-a",
        hook_event="PreToolUse",
        now=NOW + timedelta(seconds=1),
    )

    assert lease is not None
    complete_broker_hook_lease(
        conn,
        lease_id=lease.lease_id,
        delivered=True,
        result="injected",
        now=NOW + timedelta(seconds=2),
    )
    outcome = claim_relay_job(
        conn,
        heartbeat,
        wait_seconds=0,
        broker_only=True,
        broker_lease_id=lease.lease_id,
        broker_session_id="broker-a",
        now_provider=lambda: "2026-08-22T16:00:03Z",
    )

    assert len(outcome.jobs) == 1
    assert outcome.jobs[0].wake_route == "broker"
    assert outcome.jobs[0].private_route_qualification == grant
    row = conn.execute(
        "SELECT released_at,release_reason FROM coordination_leases WHERE id=?",
        (grant.lease_id,),
    ).fetchone()
    assert row["released_at"] == "2026-08-22T16:00:03Z"
    assert row["release_reason"] == QUALIFICATION_RELEASE_REASON
