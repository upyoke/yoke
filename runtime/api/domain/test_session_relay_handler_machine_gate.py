"""The relay handler refuses a poll that cannot prove the machine it claims."""

from __future__ import annotations

from yoke_core.domain.actor_permissions import ROLE_OPERATOR, grant_actor_project_role
from yoke_core.domain.handlers import session_relay as relay_handlers
from runtime.api.domain.session_relay_handler_test_support import (
    NoCloseConnection,
    claim_payload,
    relay_request,
)
from runtime.api.domain.test_session_message_support import message_connection


def _authorized_connection(monkeypatch):
    conn = message_connection()
    grant_actor_project_role(
        conn,
        actor_id=13,
        project_id=1,
        role_name=ROLE_OPERATOR,
    )
    from yoke_core.domain import db_helpers

    monkeypatch.setattr(db_helpers, "connect", lambda: NoCloseConnection(conn))
    return conn


def test_claim_without_a_machine_proof_is_refused_before_the_heartbeat(
    monkeypatch,
) -> None:
    """An unsigned poll never becomes a relay row, whatever else it carries."""
    conn = _authorized_connection(monkeypatch)
    payload = claim_payload()
    payload["projects"] = [1]

    outcome = relay_handlers.handle_relay_claim(
        relay_request("session_control.relay.claim", payload, actor_id="13")
    )

    assert outcome.primary_success is False
    assert outcome.error and outcome.error.code == "machine_proof_missing"
    assert "yoke machine register" in outcome.error.message
    assert conn.execute("SELECT COUNT(*) FROM session_relays").fetchone()[0] == 0


def test_claim_for_an_unregistered_machine_is_refused_by_name(monkeypatch) -> None:
    """A signed poll from a machine this control plane never registered."""
    conn = _authorized_connection(monkeypatch)
    payload = claim_payload()
    payload["projects"] = [1]
    payload["machine_proof_issued_at"] = "2026-09-03T12:00:00Z"
    payload["machine_proof_signature"] = "c2lnbmF0dXJl"

    outcome = relay_handlers.handle_relay_claim(
        relay_request("session_control.relay.claim", payload, actor_id="13")
    )

    assert outcome.primary_success is False
    assert outcome.error and outcome.error.code == "machine_unregistered"
    assert conn.execute("SELECT COUNT(*) FROM session_relays").fetchone()[0] == 0
