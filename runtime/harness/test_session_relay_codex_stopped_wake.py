"""Regression coverage for Codex Desktop native-state wake routing."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from uuid import UUID

import pytest

from yoke_harness import session_relay_codex_app_server as app_server
from yoke_harness.session_relay_codex import CodexNativeRequest


SESSION_ID = "01a02ee1-a421-7520-81d5-a085feeac471"
INSTRUCTION = "Yoke message message-1: check your Yoke messages."
INSTRUCTION_ID = f"message:message-1:recipient:{SESSION_ID}"


class NativeStateClient:
    def __init__(self, status: str = "notLoaded", *, read_fails: bool = False) -> None:
        self.status = status
        self.read_fails = read_fails
        self.calls: list[tuple[str, dict]] = []
        self.detached_turn: str | None = None

    def _thread(self, status: str) -> dict:
        return {
            "thread": {
                "id": SESSION_ID,
                "sessionId": SESSION_ID,
                "status": {"type": status},
                "turns": [],
            }
        }

    def request(self, method: str, params: dict) -> dict:
        self.calls.append((method, params))
        if method == "thread/read":
            if self.read_fails:
                raise app_server.CodexAppServerError("stopped thread is not loaded")
            return self._thread(self.status)
        if method == "thread/resume":
            return self._thread("idle")
        if method == "turn/start":
            return {"turn": {"id": "turn-1"}}
        raise AssertionError(f"unexpected method: {method}")

    def detach_until_turn_completed(self, turn_id: str) -> None:
        self.detached_turn = turn_id

    def close(self) -> None:
        pass


def _request(
    tmp_path: Path,
    *,
    job_id: str = "attempt-1",
    target_liveness: str = "active",
) -> CodexNativeRequest:
    return CodexNativeRequest(
        job_kind="wake",
        job_id=job_id,
        surface="codex-desktop",
        surface_version="26.818.31338",
        checkout=tmp_path,
        requested_model=None,
        presentation=None,
        target_liveness=target_liveness,
        target_session_id=SESSION_ID,
        instruction_id=INSTRUCTION_ID,
        native_instruction=INSTRUCTION,
    )


def _methods(client: NativeStateClient) -> list[str]:
    return [method for method, _params in client.calls]


@pytest.mark.parametrize("scenario", ["claimed-stopped", "chain-pending-stopped"])
def test_active_yoke_session_resumes_native_not_loaded_task(
    monkeypatch,
    tmp_path: Path,
    scenario: str,
) -> None:
    client = NativeStateClient("notLoaded")
    monkeypatch.setattr(
        app_server.CodexAppServerTransport, "_client", lambda *_: client
    )

    outcome = app_server.CodexAppServerTransport(worker=True).wake(
        _request(tmp_path, job_id=scenario, target_liveness="active")
    )

    assert outcome.state == "accepted"
    assert outcome.native_session_id == SESSION_ID
    assert outcome.identity_correlated is True
    assert _methods(client) == ["thread/read", "thread/resume", "turn/start"]
    assert client.calls[1][1] == {"threadId": SESSION_ID}
    assert client.detached_turn == "turn-1"


def test_stopped_wake_uses_exact_resume_when_native_read_fails(
    monkeypatch,
    tmp_path: Path,
) -> None:
    client = NativeStateClient(read_fails=True)
    monkeypatch.setattr(
        app_server.CodexAppServerTransport, "_client", lambda *_: client
    )

    outcome = app_server.CodexAppServerTransport(worker=True).wake(
        _request(tmp_path, target_liveness="ended")
    )

    assert outcome.state == "accepted"
    assert outcome.native_session_id == SESSION_ID
    assert _methods(client) == ["thread/read", "thread/resume", "turn/start"]


def test_retry_uses_stable_client_message_identity(
    monkeypatch,
    tmp_path: Path,
) -> None:
    clients = [NativeStateClient(), NativeStateClient()]
    pending = list(clients)
    monkeypatch.setattr(
        app_server.CodexAppServerTransport,
        "_client",
        lambda *_: pending.pop(0),
    )
    first = _request(tmp_path, job_id="attempt-1")
    second = replace(first, job_id="attempt-2")
    transport = app_server.CodexAppServerTransport(worker=True)

    assert transport.wake(first).state == "accepted"
    assert transport.wake(second).state == "accepted"

    message_ids = [
        next(params for method, params in client.calls if method == "turn/start")[
            "clientUserMessageId"
        ]
        for client in clients
    ]
    assert message_ids[0] == message_ids[1]
    assert str(UUID(message_ids[0])) == message_ids[0]
