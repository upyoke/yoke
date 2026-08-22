"""Verified-actor and wire-contract boundaries for relay handlers."""

from __future__ import annotations

from yoke_contracts.api.function_call import FunctionCallRequest
from yoke_core.domain import session_relay as relay_domain
from yoke_core.domain.handlers import session_relay as relay_handlers
from yoke_core.domain.session_relay_types import RelayClaimOutcome


def _request(function: str, payload: dict, *, actor_id: str | None = "41"):
    return FunctionCallRequest.model_validate(
        {
            "function": function,
            "actor": {"actor_id": actor_id, "session_id": "machine-token"},
            "target": {"kind": "global"},
            "payload": payload,
        }
    )


def _claim_payload() -> dict:
    return {
        "relay_id": "relay-1",
        "machine_id": "11111111-1111-4111-8111-111111111111",
        "hostname": "host-1",
        "relay_version": "1.0",
        "projects": [10],
        "surfaces": {"codex-cli": "0.148.0-alpha.15"},
        "wait_seconds": 0,
    }


class _Connection:
    def close(self) -> None:
        pass


def test_claim_binds_heartbeat_to_dispatcher_verified_actor(monkeypatch) -> None:
    seen = {}

    def claim(conn, heartbeat, *, wait_seconds):
        seen.update(actor_id=heartbeat.actor_id, wait_seconds=wait_seconds)
        return RelayClaimOutcome(
            relay_id=heartbeat.relay_id,
            machine_id=heartbeat.machine_id,
            state="active",
            connected_until="2026-08-22T12:05:00Z",
            next_poll_seconds=60,
        )

    monkeypatch.setattr(relay_domain, "claim_relay_job", claim)
    from yoke_core.domain import db_helpers

    monkeypatch.setattr(db_helpers, "connect", _Connection)

    outcome = relay_handlers.handle_relay_claim(
        _request("session_control.relay.claim", _claim_payload())
    )

    assert outcome.primary_success is True
    assert seen == {"actor_id": 41, "wait_seconds": 0}


def test_report_forwards_verified_actor_and_never_accepts_payload_actor(
    monkeypatch,
) -> None:
    seen = {}

    def report(conn, **kwargs):
        seen.update(kwargs)
        return {"attempt_id": "attempt-1", "result_code": "accepted"}

    monkeypatch.setattr(relay_domain, "report_relay_job", report)
    from yoke_core.domain import db_helpers

    monkeypatch.setattr(db_helpers, "connect", _Connection)
    outcome = relay_handlers.handle_relay_report(
        _request(
            "session_control.relay.report",
            {
                "relay_id": "relay-1",
                "job_kind": "wake",
                "job_id": "attempt-1",
                "lease_id": "lease-1",
                "result": "accepted",
                "evidence": {"duration_ms": 2},
            },
        )
    )

    assert outcome.primary_success is True
    assert seen["actor_id"] == 41
    assert seen["relay_id"] == "relay-1"


def test_claim_requires_numeric_verified_actor() -> None:
    outcome = relay_handlers.handle_relay_claim(
        _request("session_control.relay.claim", _claim_payload(), actor_id=None)
    )

    assert outcome.primary_success is False
    assert outcome.error and outcome.error.code == "actor_required"
