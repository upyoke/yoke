"""Session-control handlers distinguish harness and service identities."""

from __future__ import annotations

from types import SimpleNamespace

from yoke_contracts.api.function_call import FunctionCallRequest
from yoke_core.domain.handlers import session_launch
from runtime.api.domain.session_launch_test_support import launch_connection


def _request(session_id: str) -> FunctionCallRequest:
    return FunctionCallRequest.model_validate(
        {
            "function": "session_control.launch.create",
            "actor": {"actor_id": "1", "session_id": session_id},
            "target": {"kind": "global"},
            "payload": {},
        }
    )


def test_launch_authorization_keeps_only_registered_request_session(
    monkeypatch,
) -> None:
    conn = launch_connection()
    monkeypatch.setattr(
        "yoke_core.domain.actor_permissions.permission_decision",
        lambda *_args, **_kwargs: SimpleNamespace(allowed=True),
    )

    service = session_launch._authorization(conn, _request("doorman-ui"), 10)
    harness = session_launch._authorization(conn, _request("caller"), 10)

    assert service.session_id is None
    assert harness.session_id == "caller"
