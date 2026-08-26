"""Documented Cursor CLI and ACP framing over fake native processes."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from yoke_contracts.session_control.launch_bootstrap import native_launch_bootstrap
from yoke_harness import session_relay_cursor_acp as acp_module
from yoke_harness import session_relay_cursor_cli as cli_module
from yoke_harness.session_launch_handoff import LAUNCH_CONTEXT_ENV
from yoke_harness.session_relay_cursor import CursorCreateRequest, CursorWakeRequest
from yoke_harness.session_relay_cursor_acp import CursorAcpTransport
from yoke_harness.session_relay_cursor_cli import CursorCliTransport


LAUNCH_ID = "11111111-1111-4111-8111-111111111111"
SESSION_ID = "22222222-2222-4222-8222-222222222222"
ATTESTATION = "single-use-secret"
BOOTSTRAP = native_launch_bootstrap(LAUNCH_ID)
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
        wake_mode="waiting",
        native_instruction=CHECK_INBOX,
    )


def test_cli_transport_offers_no_create_operation_at_all(tmp_path: Path) -> None:
    # Removing the print-mode create is the containment fix, not a rename:
    # nothing may reach a launch through this transport.
    assert not hasattr(CursorCliTransport(), "create_chat")


def test_cli_wake_spawns_the_exact_session_with_no_launch_identity(
    monkeypatch,
    tmp_path: Path,
) -> None:
    spawns = []
    monkeypatch.setenv("CODEX_SESSION_ID", "parent-session")
    monkeypatch.setenv("YOKE_EXECUTOR", "codex")
    monkeypatch.setattr(
        cli_module, "resolve_native_cli", lambda _name: "/opt/cursor-agent"
    )

    def spawn(command, **kwargs):
        spawns.append((command, kwargs))
        return RunningProcess()

    result = CursorCliTransport(process_factory=spawn).resume_chat(
        _wake_request(tmp_path)
    )

    assert result.result_code == "accepted"
    command, options = spawns[0]
    assert command[:3] == ["/opt/cursor-agent", "--resume", SESSION_ID]
    assert "--trust" in command
    assert command[-1] == CHECK_INBOX
    assert "CODEX_SESSION_ID" not in options["env"]
    assert options["env"]["YOKE_EXECUTOR"] == "cursor"
    assert options["env"]["YOKE_PROVIDER"] == "cursor"
    assert options["env"]["CURSOR_INVOKED_AS"] == "cursor-agent"
    # A wake carries no launch, so it must not carry a launch attestation.
    assert LAUNCH_CONTEXT_ENV not in options["env"]


def test_cli_wake_refuses_an_inexact_session_before_spawn(
    monkeypatch,
    tmp_path: Path,
) -> None:
    spawns = []
    monkeypatch.setattr(
        cli_module, "resolve_native_cli", lambda _name: "/opt/cursor-agent"
    )
    request = _wake_request(tmp_path)
    request = CursorWakeRequest(
        checkout=request.checkout,
        target_session_id="not-an-id",
        surface_version=request.surface_version,
        target_liveness=request.target_liveness,
        wake_mode=request.wake_mode,
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
        self.new_session_id = None
        self.new_session_result = None
        self.process = SimpleNamespace(pid=4321)

    def request(self, method, params):
        self.requests.append((method, params))
        if method == "session/new":
            if self.new_session_result is not None:
                return self.new_session_result
            if self.new_session_id:
                return {"sessionId": self.new_session_id}
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
    transport = CursorAcpTransport(worker=True)
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


def test_acp_launch_creates_a_session_and_makes_it_containable(
    monkeypatch,
    tmp_path: Path,
) -> None:
    recorded = []
    client = FakeAcpClient()
    client.new_session_id = SESSION_ID
    transport = CursorAcpTransport(worker=True)
    monkeypatch.setattr(transport, "_client", lambda _checkout, _request: client)
    monkeypatch.setattr(
        acp_module,
        "record_supervised_native",
        lambda launch_id, pid, native_session_id=None: recorded.append(
            (launch_id, pid, native_session_id)
        ),
    )

    result = transport.new_session(_create_request(tmp_path))

    assert result.result_code == "native_created"
    assert result.native_session_id == SESSION_ID
    assert client.requests == [
        (
            "session/new",
            {
                "cwd": str(tmp_path.resolve()),
                "mcpServers": [],
                "model": "composer-2",
            },
        )
    ]
    assert client.prompts == [(SESSION_ID, BOOTSTRAP)]
    # The relay owns the process, so it records what it would have to kill.
    assert recorded == [(LAUNCH_ID, client.process.pid, SESSION_ID)]


def test_acp_launch_parse_failure_carries_output_snippet(
    monkeypatch,
    tmp_path: Path,
) -> None:
    client = FakeAcpClient()
    client.new_session_result = {
        "modes": {"currentModeId": "agent"},
        "models": {"currentModelId": "default[]"},
    }
    transport = CursorAcpTransport(worker=True)
    monkeypatch.setattr(transport, "_client", lambda _checkout, _request: client)

    result = transport.new_session(_create_request(tmp_path))

    assert result.result_code == "not_created"
    assert result.native_session_id is None
    assert "currentModeId" in (result.identity_output_snippet or "")
    assert result.identity_parse_expectation
    assert client.closed is True
    assert client.prompts == []
