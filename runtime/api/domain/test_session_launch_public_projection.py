"""Operator-safe launch result projection at the registered-function boundary."""

from __future__ import annotations

import json

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers import session_launch as handlers
from yoke_core.domain.session_launch_projection import public_launch_record
from yoke_core.domain.session_launch_store import get_launch
from runtime.api.domain.session_launch_test_support import (
    add_relay,
    assigned_launch,
    authorization,
    launch_connection,
)


class _NoCloseConnection:
    def __init__(self, conn):
        self._conn = conn

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def close(self) -> None:
        pass


def _request(function: str, payload: dict) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(actor_id="1", session_id="caller"),
        target=TargetRef(kind="global"),
        payload=payload,
    )


def _prepared_launch(conn):
    add_relay(conn)
    launch = assigned_launch(conn, key="safe-launch-result")
    conn.execute(
        "UPDATE session_launches SET native_session_id=?,registered_session_id=?,"
        "result_code=?,result_evidence=?,attestation_hash=?,deadline_at=? "
        "WHERE launch_id=?",
        (
            "caller",
            "caller",
            "native_created",
            json.dumps(
                {
                    "adapter_revision": "adapter-v2",
                    "duration_ms": 17,
                    "stdout": "secret output",
                    "stderr": "secret error",
                    "argv": ["secret", "argument"],
                    "body": "secret body",
                    "token": "secret token",
                }
            ),
            "sha256:secret-attestation",
            "2099-01-01T00:00:00Z",
            launch.launch_id,
        ),
    )
    conn.commit()
    return get_launch(conn, launch.launch_id)


def _wire(monkeypatch, conn, *, operator: bool = True) -> None:
    monkeypatch.setattr(handlers, "_open", lambda: _NoCloseConnection(conn))
    monkeypatch.setattr(handlers, "_resolve_project", lambda _conn, _project: 10)
    monkeypatch.setattr(
        handlers,
        "_authorization",
        lambda _conn, _request, _project_id: authorization(operator=operator),
    )


def test_public_launch_record_uses_one_allowlisted_evidence_projection() -> None:
    conn = launch_connection()
    launch = _prepared_launch(conn)

    projected = public_launch_record(launch)

    assert projected["native_session_id"] == "caller"
    assert projected["registered_session_id"] == "caller"
    assert projected["result_evidence"] == {
        "adapter_revision": "adapter-v2",
        "duration_ms": 17,
    }
    assert {
        "attestation_hash",
        "message_id",
        "idempotency_key",
        "requester_actor_id",
        "requester_session_id",
    }.isdisjoint(projected)
    assert "secret" not in json.dumps(projected)


def test_get_and_list_return_the_safe_projection_after_operator_auth(
    monkeypatch,
) -> None:
    conn = launch_connection()
    launch = _prepared_launch(conn)
    _wire(monkeypatch, conn)

    fetched = handlers.handle_launch_get(
        _request("session_control.launch.get", {"launch_id": launch.launch_id})
    )
    listed = handlers.handle_launch_list(
        _request("session_control.launch.list", {"project": "launch-project"})
    )

    assert fetched.primary_success
    assert listed.primary_success
    for row in [fetched.result_payload["launch"], *listed.result_payload["launches"]]:
        assert row["result_evidence"] == {
            "adapter_revision": "adapter-v2",
            "duration_ms": 17,
        }
        assert "message_id" not in row
        assert "attestation_hash" not in row


def test_safe_projection_does_not_weaken_project_operator_authorization(
    monkeypatch,
) -> None:
    conn = launch_connection()
    launch = _prepared_launch(conn)
    _wire(monkeypatch, conn, operator=False)

    outcome = handlers.handle_launch_get(
        _request("session_control.launch.get", {"launch_id": launch.launch_id})
    )

    assert outcome.primary_success is False
    assert outcome.error and outcome.error.code == "permission_denied"
