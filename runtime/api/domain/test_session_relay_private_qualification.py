"""Relay wake jobs consume exact private-route grants before exposure."""

from __future__ import annotations

from datetime import timedelta

import pytest

from yoke_contracts.session_control.private_route_qualification import (
    QUALIFICATION_RELEASE_REASON,
    PrivateRouteQualificationScope,
)
from yoke_core.domain.actor_permissions import (
    ROLE_ADMIN,
    grant_actor_project_role,
)
from yoke_core.domain.session_message_service import send_message
from yoke_core.domain.session_relay import claim_relay_job
from yoke_core.domain.session_relay_types import RelayHeartbeat
from yoke_core.domain.session_private_route_qualification import (
    open_qualification_grant,
)
from runtime.api.domain.test_session_message_support import (
    NOW,
    add_coordination_claim_schema,
    message_connection,
    selector,
)
from runtime.api.tools.test_session_control_live_acceptance_policy_support import (
    require_exact_cli_idle_policy,
)


RELEASE_SHA = "a" * 40
MACHINE_ID = "11111111-1111-4111-8111-111111111111"


@pytest.fixture(autouse=True)
def _candidate_route_requires_grant(monkeypatch) -> None:
    require_exact_cli_idle_policy(monkeypatch)


def _connection(*, target_version: str):
    conn = message_connection()
    add_coordination_claim_schema(conn)
    conn.execute("ALTER TABLE harness_sessions ADD COLUMN actor_id INTEGER")
    conn.execute("ALTER TABLE harness_sessions ADD COLUMN mode TEXT")
    conn.execute(
        "UPDATE harness_sessions SET actor_id=10,mode='operator' WHERE session_id='s1'"
    )
    # Activity is a full day old so the target is idle under any staleness
    # window, pinning the wake to the private idle route rather than leaving
    # it to resolve near the boundary.
    idle_since = str(NOW - timedelta(days=1))
    conn.execute(
        "UPDATE harness_sessions SET executor_surface='claude-cli',"
        "executor_version=?,machine_id=?,turn_posture='running',"
        "turn_posture_at=?,last_heartbeat=?,last_tool_call_at=? "
        "WHERE session_id='s2'",
        (target_version, MACHINE_ID, idle_since, idle_since, idle_since),
    )
    grant_actor_project_role(
        conn,
        actor_id=10,
        project_id=1,
        role_name=ROLE_ADMIN,
    )
    conn.commit()
    return conn


def _heartbeat(version: str) -> RelayHeartbeat:
    return RelayHeartbeat(
        relay_id=f"machine:{MACHINE_ID}",
        actor_id=10,
        machine_id=MACHINE_ID,
        hostname="stage-relay",
        relay_version="0.1.1",
        surface_versions={"claude-cli": version},
        project_ids=(1,),
    )


def _send(conn, *, run_id: str) -> str:
    return str(
        send_message(
            conn,
            actor_id=10,
            sender_session_id="s1",
            selector=selector(session_ids=["s2"]),
            body="Body remains server-side during native wake.",
            idempotency_key=f"fleet-live:{run_id}:claude-cli:wake",
            now=NOW,
        )["message_id"]
    )


def test_candidate_direct_wake_consumes_grant_before_return(monkeypatch) -> None:
    monkeypatch.setenv("YOKE_ENVIRONMENT", "stage")
    monkeypatch.setenv("YOKE_BUILD_SHA", RELEASE_SHA)
    conn = _connection(target_version="2.1.241")
    scope = PrivateRouteQualificationScope(
        release_sha=RELEASE_SHA,
        acceptance_run_id="stage-proof-relay",
        surface="claude-cli",
        version="2.1.241",
        operation="message_idle",
        route="direct",
    )
    grant = open_qualification_grant(
        conn,
        project_id=1,
        sender_session_id="s1",
        operator_actor_id=10,
        scope=scope,
    )
    message_id = _send(conn, run_id="stage-proof-relay")

    outcome = claim_relay_job(
        conn,
        _heartbeat("2.1.241"),
        wait_seconds=0,
        now_provider=lambda: "2026-08-22T16:11:00Z",
    )

    assert len(outcome.jobs) == 1
    assert outcome.jobs[0].message_id == message_id
    assert outcome.jobs[0].wake_route == "direct"
    assert outcome.jobs[0].private_route_qualification == grant
    wire = outcome.to_dict()["jobs"][0]
    assert wire["private_route_qualification"]["grant_digest"] == scope.digest
    assert "lease_key" not in repr(wire)
    assert "Body remains" not in repr(wire)
    row = conn.execute(
        "SELECT released_at,release_reason_intent FROM work_claims WHERE id=?",
        (grant.lease_id,),
    ).fetchone()
    assert row["released_at"] == "2026-08-22T16:11:00Z"
    assert row["release_reason_intent"] == QUALIFICATION_RELEASE_REASON


def test_candidate_without_exact_grant_remains_unclaimed(monkeypatch) -> None:
    monkeypatch.setenv("YOKE_ENVIRONMENT", "stage")
    monkeypatch.setenv("YOKE_BUILD_SHA", RELEASE_SHA)
    conn = _connection(target_version="2.1.241")
    _send(conn, run_id="stage-proof-missing")

    outcome = claim_relay_job(
        conn,
        _heartbeat("2.1.241"),
        wait_seconds=0,
        now_provider=lambda: "2026-08-22T16:11:00Z",
    )

    assert outcome.jobs == ()
    assert (
        conn.execute(
            "SELECT wake_attempt_count FROM session_message_recipients"
        ).fetchone()[0]
        == 0
    )


def test_canonical_version_stays_first_and_needs_no_grant(monkeypatch) -> None:
    monkeypatch.setenv("YOKE_ENVIRONMENT", "prod")
    monkeypatch.setenv("YOKE_BUILD_SHA", "b" * 40)
    conn = _connection(target_version="2.1.238")
    _send(conn, run_id="canonical-route")

    outcome = claim_relay_job(
        conn,
        _heartbeat("2.1.238"),
        wait_seconds=0,
        now_provider=lambda: "2026-08-22T16:11:00Z",
    )

    assert len(outcome.jobs) == 1
    assert outcome.jobs[0].private_route_qualification is None
