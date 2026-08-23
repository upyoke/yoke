"""Active-hook qualification must never poison an ordinary message ack."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from yoke_contracts.session_control.private_route_qualification import (
    QUALIFICATION_RELEASE_REASON,
    QUALIFICATION_TTL_SECONDS,
    PrivateRouteQualificationScope,
)
from yoke_core.domain.actor_permissions import ROLE_ADMIN, grant_actor_project_role
from yoke_core.domain.session_message_service import acknowledge_message, send_message
from yoke_core.domain.session_private_route_qualification import (
    consume_qualification_grant,
    open_qualification_grant,
)
from runtime.api.domain.test_session_message_support import (
    add_coordination_lease_schema,
    message_connection,
    selector,
)


RELEASE_SHA = "a" * 40


def _setup(monkeypatch):
    monkeypatch.setenv("YOKE_ENVIRONMENT", "stage")
    monkeypatch.setenv("YOKE_BUILD_SHA", RELEASE_SHA)
    conn = message_connection()
    add_coordination_lease_schema(conn)
    conn.execute("ALTER TABLE harness_sessions ADD COLUMN actor_id INTEGER")
    conn.execute("ALTER TABLE harness_sessions ADD COLUMN mode TEXT")
    conn.execute(
        "UPDATE harness_sessions SET actor_id=10,mode='operator' WHERE session_id='s1'"
    )
    conn.execute(
        "UPDATE harness_sessions SET executor='claude',"
        "executor_surface='claude-desktop',executor_version='1.34493.1' "
        "WHERE session_id='s2'"
    )
    grant_actor_project_role(conn, actor_id=10, project_id=1, role_name=ROLE_ADMIN)
    current = datetime.now(timezone.utc).replace(microsecond=0)
    grant = open_qualification_grant(
        conn,
        project_id=1,
        sender_session_id="s1",
        operator_actor_id=10,
        scope=PrivateRouteQualificationScope(
            release_sha=RELEASE_SHA,
            acceptance_run_id="desktop-active-proof",
            surface="claude-desktop",
            version="1.34493.1",
            operation="message_active",
            route="hook",
        ),
    )
    message = send_message(
        conn,
        actor_id=10,
        sender_session_id="s1",
        selector=selector(session_ids=["s2"]),
        body="Acknowledge the active-hook proof.",
        idempotency_key="fleet-live:desktop-active-proof:desktop:initial",
        now=current,
    )
    conn.execute(
        "UPDATE session_message_recipients SET state='injected',injection_count=1,"
        "last_injected_at=? WHERE message_id=? AND session_id='s2'",
        (current.isoformat(), message["message_id"]),
    )
    conn.commit()
    return conn, grant, str(message["message_id"]), current


def test_valid_active_hook_ack_consumes_the_exact_grant(monkeypatch) -> None:
    conn, grant, message_id, current = _setup(monkeypatch)

    result = acknowledge_message(
        conn, message_id=message_id, session_id="s2", now=current
    )

    assert result["recipients"][0]["state"] == "acknowledged"
    row = conn.execute(
        "SELECT release_reason,released_by_session_id,released_by_actor_id "
        "FROM coordination_leases WHERE id=?",
        (grant.lease_id,),
    ).fetchone()
    assert tuple(row) == (QUALIFICATION_RELEASE_REASON, "s1", "10")


@pytest.mark.parametrize("failure", ["expired", "inactive", "consumed"])
def test_qualification_failure_preserves_normal_ack(monkeypatch, failure: str) -> None:
    conn, grant, message_id, current = _setup(monkeypatch)
    ack_at = current
    if failure == "expired":
        opened = datetime.fromisoformat(grant.opened_at.replace("Z", "+00:00"))
        ack_at = opened + timedelta(seconds=QUALIFICATION_TTL_SECONDS)
    elif failure == "inactive":
        conn.execute(
            "UPDATE harness_sessions SET ended_at=? WHERE session_id='s1'",
            (current.isoformat(),),
        )
        conn.commit()
    else:
        consume_qualification_grant(conn, grant)

    result = acknowledge_message(
        conn, message_id=message_id, session_id="s2", now=ack_at
    )

    assert result["recipients"][0]["state"] == "acknowledged"
    row = conn.execute(
        "SELECT released_at,release_reason FROM coordination_leases WHERE id=?",
        (grant.lease_id,),
    ).fetchone()
    if failure == "consumed":
        assert row["release_reason"] == QUALIFICATION_RELEASE_REASON
    else:
        assert row["released_at"] is None
        assert row["release_reason"] is None
