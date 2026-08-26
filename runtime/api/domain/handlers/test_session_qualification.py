"""Handler, registry, and reserved-key boundaries for stage qualification."""

from __future__ import annotations

import pytest

from runtime.api.tools.test_session_control_live_acceptance_policy_support import (
    require_exact_cli_idle_policy,
)
from yoke_cli.commands.adapters.session_control_qualification import (
    QUALIFICATION_OPEN_USAGE,
)
from yoke_contracts.api.function_call import FunctionCallRequest
from yoke_contracts.session_control.private_route_qualification import (
    QUALIFICATION_LEASE_PREFIX,
    QUALIFICATION_RELEASE_REASON,
)
from yoke_core.domain.actor_permissions import (
    ROLE_ADMIN,
    grant_actor_project_role,
)
from yoke_core.api.service_client_structured_api_adapter import adapter_for
from yoke_core.domain.handlers import (
    _register_session_control,
    claims_coordination_claim,
    session_qualification,
)
from yoke_core.domain import yoke_function_registry
from runtime.api.domain.test_session_message_support import (
    add_coordination_lease_schema,
    message_connection,
)


RELEASE_SHA = "a" * 40


@pytest.fixture(autouse=True)
def _unproven_private_route_policy(monkeypatch) -> None:
    """Give handler tests an explicit stage-qualification candidate."""
    require_exact_cli_idle_policy(monkeypatch)


class _NoCloseConnection:
    def __init__(self, conn) -> None:
        self._conn = conn

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def close(self) -> None:
        pass


def _connection():
    conn = message_connection()
    add_coordination_lease_schema(conn)
    conn.execute("ALTER TABLE harness_sessions ADD COLUMN actor_id INTEGER")
    conn.execute("ALTER TABLE harness_sessions ADD COLUMN mode TEXT")
    conn.execute(
        "UPDATE harness_sessions SET actor_id=10,mode='operator' WHERE session_id='s1'"
    )
    grant_actor_project_role(
        conn,
        actor_id=10,
        project_id=1,
        role_name=ROLE_ADMIN,
    )
    conn.commit()
    return conn


def _request(
    *,
    actor_id: str | None = "10",
    session_id: str = "s1",
    project: str = "alpha",
    subagent_execution: bool = False,
) -> FunctionCallRequest:
    return FunctionCallRequest.model_validate(
        {
            "function": "session_control.qualification.open",
            "actor": {"actor_id": actor_id, "session_id": session_id},
            "target": {"kind": "global"},
            "options": {"subagent_execution": subagent_execution},
            "payload": {
                "project": project,
                "environment": "stage",
                "release_sha": RELEASE_SHA,
                "acceptance_run_id": "stage-proof-1",
                "surface": "claude-cli",
                "version": "2.1.241",
                "operation": "message_idle",
                "route": "direct",
            },
        }
    )


def test_handler_refuses_subagent_attestation() -> None:
    outcome = session_qualification.handle_qualification_open(
        _request(subagent_execution=True)
    )

    assert outcome.error and outcome.error.code == "subagent_qualification_forbidden"
    assert outcome.error.jsonpath == "$.options.subagent_execution"
    assert "registered top-level session" in outcome.error.message


def test_registration_is_operator_override_and_stage_guarded() -> None:
    yoke_function_registry.reset_registry_for_tests()
    try:
        _register_session_control.register(yoke_function_registry)
        entry = yoke_function_registry.lookup("session_control.qualification.open")
        assert entry is not None
        assert entry.claim_required_kind == "operator_override"
        assert entry.side_effects == ("work_claims_insert",)
        assert entry.target_kinds == ("global",)
        assert "stage_only_exact_release" in entry.guardrails
        adapter = adapter_for("session_control.qualification.open")
        assert adapter is not None
        assert adapter.cli_invocation == QUALIFICATION_OPEN_USAGE
        assert adapter.agent_path == "operator-only"
        acknowledge = yoke_function_registry.lookup(
            "session_control.message.acknowledge"
        )
        relay_claim = yoke_function_registry.lookup("session_control.relay.claim")
        assert acknowledge is not None
        assert relay_claim is not None
        assert "work_claims_update_released_at" in acknowledge.side_effects
        assert "work_claims_update_released_at" in relay_claim.side_effects
    finally:
        yoke_function_registry.reset_registry_for_tests()


def test_handler_opens_for_registered_project_admin_only(monkeypatch) -> None:
    monkeypatch.setenv("YOKE_ENVIRONMENT", "stage")
    monkeypatch.setenv("YOKE_BUILD_SHA", RELEASE_SHA)
    conn = _connection()
    monkeypatch.setattr(
        "yoke_core.domain.db_helpers.connect",
        lambda: _NoCloseConnection(conn),
    )

    outcome = session_qualification.handle_qualification_open(_request())

    assert outcome.primary_success is True
    grant = outcome.result_payload["grant"]
    assert grant["sender_session_id"] == "s1"
    assert grant["project_id"] == 1
    assert grant["scope"]["release_sha"] == RELEASE_SHA


def test_handler_refuses_wrong_project_actor_and_unregistered_session(
    monkeypatch,
) -> None:
    monkeypatch.setenv("YOKE_ENVIRONMENT", "stage")
    monkeypatch.setenv("YOKE_BUILD_SHA", RELEASE_SHA)
    conn = _connection()
    monkeypatch.setattr(
        "yoke_core.domain.db_helpers.connect",
        lambda: _NoCloseConnection(conn),
    )

    hidden = session_qualification.handle_qualification_open(_request(project="beta"))
    missing_actor = session_qualification.handle_qualification_open(
        _request(actor_id=None)
    )
    unknown_session = session_qualification.handle_qualification_open(
        _request(session_id="unknown")
    )

    assert hidden.error and hidden.error.code == "permission_denied"
    assert (
        missing_actor.error and missing_actor.error.code == "operator_identity_required"
    )
    assert (
        unknown_session.error
        and unknown_session.error.code == "operator_session_unregistered"
    )
    assert conn.execute(
        "SELECT COUNT(*) FROM work_claims WHERE target_kind IN "
        "('migration_serialization','qa_admission','route_qualification')"
    ).fetchone()[0] == 0


def test_ordinary_coordination_lease_cannot_forge_reserved_key() -> None:
    request = FunctionCallRequest.model_validate(
        {
            "function": "claims.coordination_lease.acquire",
            "actor": {"actor_id": "10", "session_id": "s1"},
            "target": {"kind": "global"},
            "payload": {
                "project_id": "alpha",
                "lease_key": f"{QUALIFICATION_LEASE_PREFIX}forged",
            },
        }
    )

    outcome = claims_coordination_claim.handle_acquire(request)

    assert outcome.primary_success is False
    assert outcome.error and outcome.error.code == "lease_key_reserved"


def test_reserved_grant_cannot_be_heartbeated_or_forged_released(
    monkeypatch,
) -> None:
    monkeypatch.setenv("YOKE_ENVIRONMENT", "stage")
    monkeypatch.setenv("YOKE_BUILD_SHA", RELEASE_SHA)
    conn = _connection()
    monkeypatch.setattr(claims_coordination_lease, "_connect_rw", lambda: conn)
    monkeypatch.setattr(
        "yoke_core.domain.db_helpers.connect",
        lambda: _NoCloseConnection(conn),
    )
    opened = session_qualification.handle_qualification_open(_request())
    lease_id = opened.result_payload["grant"]["lease_id"]

    def request(function: str, payload: dict[str, object]) -> FunctionCallRequest:
        return FunctionCallRequest.model_validate(
            {
                "function": function,
                "actor": {"actor_id": "10", "session_id": "s2"},
                "target": {"kind": "global"},
                "payload": payload,
            }
        )

    heartbeat = claims_coordination_claim.handle_heartbeat(
        request("claims.coordination_lease.heartbeat", {"lease_id": lease_id})
    )
    release = claims_coordination_claim.handle_release(
        request(
            "claims.coordination_lease.release",
            {"lease_id": lease_id, "reason": QUALIFICATION_RELEASE_REASON},
        )
    )

    assert heartbeat.error and heartbeat.error.code == "lease_key_reserved"
    assert release.error and release.error.code == "lease_key_reserved"
    row = conn.execute(
        "SELECT released_at,release_reason_intent FROM work_claims WHERE id=?",
        (lease_id,),
    ).fetchone()
    assert row["released_at"] is None
    assert row["release_reason"] is None
