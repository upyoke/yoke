"""Regression coverage for exact Codex Desktop stopped-thread wake."""

from __future__ import annotations

from pathlib import Path

from yoke_harness import session_relay_codex_app_server as app_server
from yoke_harness.session_relay_codex import CodexNativeRequest


SESSION_ID = "01a02ee1-a421-7520-81d5-a085feeac471"
INSTRUCTION = "Yoke message message-1: check your Yoke messages."


class ResumeOnlyClient:
    """Model a stopped task whose supported discovery path is resume."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.detached_turn: str | None = None

    def request(self, method: str, params: dict) -> dict:
        self.calls.append((method, params))
        if method == "thread/read":
            raise app_server.CodexAppServerError("stopped thread is not loaded")
        if method == "thread/resume":
            return {
                "thread": {
                    "id": SESSION_ID,
                    "sessionId": SESSION_ID,
                    "status": {"type": "idle"},
                    "turns": [],
                }
            }
        if method == "turn/start":
            return {"turn": {"id": "turn-1"}}
        raise AssertionError(f"unexpected method: {method}")

    def detach_until_turn_completed(self, turn_id: str) -> None:
        self.detached_turn = turn_id

    def close(self) -> None:
        pass


def test_ended_wake_resumes_exact_identity_without_pre_read(
    monkeypatch,
    tmp_path: Path,
) -> None:
    client = ResumeOnlyClient()
    monkeypatch.setattr(
        app_server.CodexAppServerTransport, "_client", lambda *_: client
    )
    request = CodexNativeRequest(
        job_kind="wake",
        job_id="attempt-1",
        surface="codex-desktop",
        surface_version="26.818.31338",
        checkout=tmp_path,
        requested_model=None,
        presentation=None,
        target_liveness="ended",
        target_session_id=SESSION_ID,
        native_instruction=INSTRUCTION,
    )

    outcome = app_server.CodexAppServerTransport(worker=True).wake(request)

    assert outcome.state == "accepted"
    assert outcome.native_session_id == SESSION_ID
    assert outcome.identity_correlated is True
    assert [method for method, _params in client.calls] == [
        "thread/resume",
        "turn/start",
    ]
    assert client.calls[0][1] == {"threadId": SESSION_ID}
    assert client.calls[1][1]["threadId"] == SESSION_ID
    assert client.calls[1][1]["input"][0]["text"] == INSTRUCTION
    assert client.detached_turn == "turn-1"
