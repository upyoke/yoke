"""Wire-shaped helpers shared by the relay-handler test modules."""

from __future__ import annotations

from yoke_contracts.api.function_call import FunctionCallRequest


def relay_request(function: str, payload: dict, *, actor_id: str | None = "41"):
    return FunctionCallRequest.model_validate(
        {
            "function": function,
            "actor": {"actor_id": actor_id, "session_id": "machine-token"},
            "target": {"kind": "global"},
            "payload": payload,
        }
    )


def claim_payload() -> dict:
    return {
        "relay_id": "relay-1",
        "machine_id": "11111111-1111-4111-8111-111111111111",
        "hostname": "host-1",
        "relay_version": "1.0",
        "projects": [10],
        "surfaces": {"codex-cli": "0.148.0-alpha.15"},
        "wait_seconds": 0,
    }


class Connection:
    def close(self) -> None:
        pass


class NoCloseConnection:
    def __init__(self, conn):
        self._conn = conn

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def close(self) -> None:
        pass


def machine_is_proved(monkeypatch) -> None:
    """Stand the machine-identity gate down for wire-contract tests.

    Those tests are about actor binding and lease forwarding. The gate itself
    is covered by ``test_machine_registry_relay_guard`` and by
    ``test_session_relay_handler_machine_gate``, so stubbing it here keeps
    each test to one subject.
    """
    monkeypatch.setattr(
        "yoke_core.domain.machine_registry_relay_guard.require_proved_machine",
        lambda *_args, **_kwargs: None,
    )


__all__ = [
    "Connection",
    "NoCloseConnection",
    "claim_payload",
    "machine_is_proved",
    "relay_request",
]
