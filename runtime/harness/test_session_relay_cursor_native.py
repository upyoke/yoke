"""Documented Cursor CLI and ACP framing over fake native processes."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from yoke_harness import session_relay_cursor_cli as cli_module
from yoke_harness.session_launch_handoff import LAUNCH_CONTEXT_ENV
from yoke_harness.session_relay_cursor import CursorCreateRequest, CursorWakeRequest
from yoke_harness.session_relay_cursor_acp import CursorAcpTransport
from yoke_harness.session_relay_cursor_cli import CursorCliTransport


LAUNCH_ID = "11111111-1111-4111-8111-111111111111"
SESSION_ID = "22222222-2222-4222-8222-222222222222"
ATTESTATION = "single-use-secret"
BOOTSTRAP = f"Yoke launch `{LAUNCH_ID}`: register, pull your message, act."
CHECK_INBOX = "Yoke message message-1: check your Yoke messages."


class RunningProcess:
    def wait(self, timeout=None):
        if timeout == cli_module._STARTUP_SETTLE_SECONDS:
            raise cli_module.subprocess.TimeoutExpired("cursor-agent", timeout)
        return 0


def _create_request(tmp_path: Path) -> CursorCreateRequest:
    return CursorCreateRequest(
        checkout=tmp_path,
        launch_id=LAUNCH_ID,
        surface_version="2026.08.11-e8db854",
        native_instruction=BOOTSTRAP,
        launch_attestation=ATTESTATION,
        requested_model="composer-2",
    )


def _wake_request(tmp_path: Path) -> CursorWakeRequest:
    return CursorWakeRequest(
        checkout=tmp_path,
        target_session_id=SESSION_ID,
        surface_version="2026.08.11-e8db854",
        target_liveness="ended",
        native_instruction=CHECK_INBOX,
    )


def test_cli_create_uses_empty_chat_then_exact_headless_resume(
    monkeypatch,
    tmp_path: Path,
) -> None:
    calls = []
    spawns = []
    monkeypatch.setenv("CODEX_SESSION_ID", "parent-session")
    monkeypatch.setenv("CODEX_THREAD_ID", "parent-thread")
    monkeypatch.setenv("YOKE_EXECUTOR", "codex")
    monkeypatch.setattr(cli_module.shutil, "which", lambda _name: "/opt/cursor-agent")

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout=f"{SESSION_ID}\n")

    def spawn(command, **kwargs):
        spawns.append((command, kwargs))
        return RunningProcess()

    result = CursorCliTransport(
        command_runner=run,
        process_factory=spawn,
    ).create_chat(_create_request(tmp_path))

    assert calls[0][0] == ["/opt/cursor-agent", "create-chat"]
    assert result.result_code == "native_created"
    assert result.native_session_id == SESSION_ID
    command, options = spawns[0]
    assert command[:3] == ["/opt/cursor-agent", "--resume", SESSION_ID]
    assert command[-1] == BOOTSTRAP
    assert "--model" in command
    assert ATTESTATION not in repr(command)
    assert "CODEX_SESSION_ID" not in calls[0][1]["env"]
    assert "CODEX_THREAD_ID" not in options["env"]
    assert options["env"]["YOKE_EXECUTOR"] == "cursor"
    assert options["env"]["YOKE_EXECUTOR_VERSION"] == "2026.08.11-e8db854"
    assert options["env"]["YOKE_PROVIDER"] == "cursor"
    assert options["env"]["CURSOR_INVOKED_AS"] == "cursor-agent"
    assert json.loads(options["env"][LAUNCH_CONTEXT_ENV]) == {
        "launch_id": LAUNCH_ID,
        "attestation": ATTESTATION,
    }


def test_cli_wake_refuses_an_inexact_session_before_spawn(
    monkeypatch,
    tmp_path: Path,
) -> None:
    spawns = []
    monkeypatch.setattr(cli_module.shutil, "which", lambda _name: "/opt/cursor-agent")
    request = _wake_request(tmp_path)
    request = CursorWakeRequest(
        checkout=request.checkout,
        target_session_id="not-an-id",
        surface_version=request.surface_version,
        target_liveness=request.target_liveness,
        native_instruction=request.native_instruction,
    )

    result = CursorCliTransport(
        process_factory=lambda *args, **kwargs: spawns.append((args, kwargs))
    ).resume_chat(request)

    assert result.result_code == "not_found"
    assert spawns == []


class FakeAcpClient:
    def __init__(self) -> None:
        self.requests = []
        self.prompts = []
        self.closed = False

    def request(self, method, params):
        self.requests.append((method, params))
        return {}

    def start_prompt(self, session_id, instruction):
        self.prompts.append((session_id, instruction))

    def close(self):
        self.closed = True


def test_acp_idle_wake_loads_and_prompts_the_exact_session(
    monkeypatch,
    tmp_path: Path,
) -> None:
    client = FakeAcpClient()
    transport = CursorAcpTransport()
    monkeypatch.setattr(transport, "_client", lambda _checkout, _request: client)

    result = transport.prompt_session(_wake_request(tmp_path))

    assert result.result_code == "accepted"
    assert client.requests == [
        (
            "session/load",
            {"cwd": str(tmp_path.resolve()), "mcpServers": [], "sessionId": SESSION_ID},
        )
    ]
    assert client.prompts == [(SESSION_ID, CHECK_INBOX)]
