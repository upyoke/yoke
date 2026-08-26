"""Fail-closed authority tests for one-shot private-route qualification."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from runtime.api.tools.test_session_control_live_acceptance_policy_support import (
    require_exact_cli_idle_policy,
)
from yoke_contracts.session_control.private_route_qualification import (
    QUALIFICATION_ABANDONED_REASON,
    QUALIFICATION_RELEASE_REASON,
    QUALIFICATION_TTL_SECONDS,
    PrivateRouteQualificationScope,
)
from yoke_core.domain.actor_permissions import (
    ROLE_ADMIN,
    grant_actor_project_role,
)
from yoke_core.domain.coordination_claims import get_claim
from yoke_core.domain.session_private_route_qualification import (
    PrivateRouteQualificationError,
    consume_qualification_grant,
    grant_from_lease,
    open_qualification_grant,
    qualification_for_message,
)
from runtime.api.domain.test_session_message_support import (
    add_coordination_lease_schema,
    message_connection,
)


RELEASE_SHA = "a" * 40


@pytest.fixture(autouse=True)
def _unproven_private_route_policy(monkeypatch) -> None:
    """Give stage-qualification tests an explicit noncanonical candidate."""
    require_exact_cli_idle_policy(monkeypatch)


def _connection():
    conn = message_connection()
    add_coordination_lease_schema(conn)
    conn.execute("ALTER TABLE harness_sessions ADD COLUMN actor_id INTEGER")
    conn.execute("ALTER TABLE harness_sessions ADD COLUMN mode TEXT")
    conn.execute(
        "UPDATE harness_sessions SET actor_id=10,mode='operator',"
        "executor_surface='claude-cli',executor_version='2.1.241' "
        "WHERE session_id='s1'"
    )
    grant_actor_project_role(
        conn,
        actor_id=10,
        project_id=1,
        role_name=ROLE_ADMIN,
    )
    conn.commit()
    return conn


def _scope(*, run_id: str = "stage-proof-1") -> PrivateRouteQualificationScope:
    return PrivateRouteQualificationScope(
        release_sha=RELEASE_SHA,
        acceptance_run_id=run_id,
        surface="claude-cli",
        version="2.1.241",
        operation="message_idle",
        route="direct",
    )


def _stage(monkeypatch) -> None:
    monkeypatch.setenv("YOKE_ENVIRONMENT", "stage")
    monkeypatch.setenv("YOKE_BUILD_SHA", RELEASE_SHA)


def test_opened_grant_has_fixed_ttl_and_consumes_exactly_once(monkeypatch) -> None:
    _stage(monkeypatch)
    conn = _connection()
    grant = open_qualification_grant(
        conn,
        project_id=1,
        sender_session_id="s1",
        operator_actor_id=10,
        scope=_scope(),
    )

    opened = datetime.fromisoformat(grant.opened_at.replace("Z", "+00:00"))
    expires = datetime.fromisoformat(grant.expires_at.replace("Z", "+00:00"))
    assert (expires - opened).total_seconds() == QUALIFICATION_TTL_SECONDS
    assert grant.grant_digest == grant.scope.digest
    assert grant.scope.lease_key not in repr(grant.model_dump(exclude={"scope"}))

    consume_qualification_grant(conn, grant)
    row = conn.execute(
        "SELECT released_at,release_reason FROM coordination_leases WHERE id=?",
        (grant.lease_id,),
    ).fetchone()
    assert row["released_at"]
    assert row["release_reason"] == QUALIFICATION_RELEASE_REASON
    with pytest.raises(PrivateRouteQualificationError) as consumed:
        consume_qualification_grant(conn, grant)
    assert consumed.value.code == "qualification_grant_consumed"


@pytest.mark.parametrize(
    ("environment", "build", "code"),
    [
        ("prod", RELEASE_SHA, "qualification_stage_only"),
        ("stage", "b" * 40, "qualification_release_mismatch"),
        ("stage", "a" * 12, "qualification_release_mismatch"),
    ],
)
def test_open_refuses_prod_or_nonexact_serving_sha(
    monkeypatch, environment: str, build: str, code: str
) -> None:
    monkeypatch.setenv("YOKE_ENVIRONMENT", environment)
    monkeypatch.setenv("YOKE_BUILD_SHA", build)
    conn = _connection()

    with pytest.raises(PrivateRouteQualificationError) as denied:
        open_qualification_grant(
            conn,
            project_id=1,
            sender_session_id="s1",
            operator_actor_id=10,
            scope=_scope(),
        )

    assert denied.value.code == code
    assert conn.execute("SELECT COUNT(*) FROM coordination_leases").fetchone()[0] == 0


def test_open_refuses_canonical_floor_and_inactive_operator(monkeypatch) -> None:
    _stage(monkeypatch)
    conn = _connection()
    canonical_floor = _scope().model_copy(update={"version": "2.1.238"})
    with pytest.raises(PrivateRouteQualificationError) as canonical:
        open_qualification_grant(
            conn,
            project_id=1,
            sender_session_id="s1",
            operator_actor_id=10,
            scope=canonical_floor,
        )
    assert canonical.value.code == "qualification_canonical_route"

    conn.execute("UPDATE harness_sessions SET mode='agent' WHERE session_id='s1'")
    with pytest.raises(PrivateRouteQualificationError) as inactive:
        open_qualification_grant(
            conn,
            project_id=1,
            sender_session_id="s1",
            operator_actor_id=10,
            scope=_scope(),
        )
    assert inactive.value.code == "qualification_owner_inactive"


def test_grant_rechecks_owner_and_expiry_after_open(monkeypatch) -> None:
    _stage(monkeypatch)
    conn = _connection()
    grant = open_qualification_grant(
        conn,
        project_id=1,
        sender_session_id="s1",
        operator_actor_id=10,
        scope=_scope(),
    )
    lease = get_lease(conn, grant.lease_id)
    opened = datetime.fromisoformat(grant.opened_at.replace("Z", "+00:00"))

    with pytest.raises(PrivateRouteQualificationError) as expired:
        grant_from_lease(
            conn,
            lease,
            grant.scope,
            now=opened + timedelta(seconds=QUALIFICATION_TTL_SECONDS),
        )
    assert expired.value.code == "qualification_grant_expired"

    conn.execute(
        "UPDATE harness_sessions SET ended_at='2026-08-23T01:00:00Z' "
        "WHERE session_id='s1'"
    )
    with pytest.raises(PrivateRouteQualificationError) as inactive:
        grant_from_lease(conn, lease, grant.scope, now=datetime.now(timezone.utc))
    assert inactive.value.code == "qualification_owner_inactive"


def test_expired_grant_is_settled_and_same_scope_can_be_rearmed(monkeypatch) -> None:
    _stage(monkeypatch)
    conn = _connection()
    first = open_qualification_grant(
        conn,
        project_id=1,
        sender_session_id="s1",
        operator_actor_id=10,
        scope=_scope(),
        now="2099-01-01T00:00:00Z",
    )

    second = open_qualification_grant(
        conn,
        project_id=1,
        sender_session_id="s1",
        operator_actor_id=10,
        scope=_scope(),
        now="2099-01-01T00:30:00Z",
    )

    assert second.lease_id != first.lease_id
    rows = conn.execute(
        "SELECT id,released_at,release_reason,released_by_session_id,"
        "released_by_actor_id FROM coordination_leases ORDER BY id"
    ).fetchall()
    assert rows[0]["release_reason"] == QUALIFICATION_ABANDONED_REASON
    assert rows[0]["released_at"] == "2099-01-01T00:30:00Z"
    assert rows[0]["released_by_session_id"] == "s1"
    assert rows[0]["released_by_actor_id"] == "10"
    assert rows[1]["released_at"] is None


def test_post_acquire_validation_failure_rolls_back_reserved_lease(
    monkeypatch,
) -> None:
    _stage(monkeypatch)
    conn = _connection()

    def fail_after_insert(*_args, **_kwargs):
        raise PrivateRouteQualificationError(
            "qualification_recheck_failed", "forced post-acquire recheck"
        )

    monkeypatch.setattr(
        "yoke_core.domain.session_private_route_qualification.grant_from_lease",
        fail_after_insert,
    )

    with pytest.raises(PrivateRouteQualificationError) as raised:
        open_qualification_grant(
            conn,
            project_id=1,
            sender_session_id="s1",
            operator_actor_id=10,
            scope=_scope(),
        )

    assert raised.value.code == "qualification_recheck_failed"
    assert conn.execute("SELECT COUNT(*) FROM coordination_leases").fetchone()[0] == 0


def test_message_lookup_binds_run_sender_project_operation_and_route(
    monkeypatch,
) -> None:
    _stage(monkeypatch)
    conn = _connection()
    grant = open_qualification_grant(
        conn,
        project_id=1,
        sender_session_id="s1",
        operator_actor_id=10,
        scope=_scope(run_id="stage-proof-candidate"),
    )
    conn.execute(
        "INSERT INTO session_messages "
        "(message_id,sender_actor_id,sender_session_id,body,body_sha256,"
        "selector_snapshot,idempotency_key,created_at,expires_at) "
        "VALUES ('message-1',10,'s1','body','digest','{}',?, ?, ?)",
        (
            "fleet-live:stage-proof-other:claude-cli:wake",
            "2026-08-23T01:00:00Z",
            "2026-08-23T02:00:00Z",
        ),
    )
    conn.commit()
    candidate = {
        "message_id": "message-1",
        "project_id": 1,
        "executor_surface": "claude-cli",
        "executor_version": "2.1.241",
    }

    assert (
        qualification_for_message(
            conn, candidate, operation="message_idle", route="direct"
        )
        is None
    )
    conn.execute(
        "UPDATE session_messages SET idempotency_key=?,sender_session_id='s2' "
        "WHERE message_id='message-1'",
        ("fleet-live:stage-proof-candidate:claude-cli:wake",),
    )
    assert (
        qualification_for_message(
            conn, candidate, operation="message_idle", route="direct"
        )
        is None
    )
    conn.execute(
        "UPDATE session_messages SET sender_session_id='s1' "
        "WHERE message_id='message-1'"
    )
    assert (
        qualification_for_message(
            conn, candidate, operation="message_idle", route="direct"
        )
        == grant
    )
    assert (
        qualification_for_message(
            conn, candidate, operation="message_idle", route="broker"
        )
        is None
    )
