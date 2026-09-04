"""Documented Cursor CLI and ACP framing over fake native processes."""

from __future__ import annotations

import io
from dataclasses import replace
from pathlib import Path
import time
from types import SimpleNamespace

from yoke_harness import session_relay_cursor_acp as acp_module
from yoke_harness import session_relay_cursor_cli as cli_module
from yoke_harness.session_launch_handoff import LAUNCH_CONTEXT_ENV
from yoke_harness.session_relay_cursor import (
    CursorNativeResult,
    build_cursor_adapter,
)
from yoke_harness.session_relay_cursor_acp import CursorAcpTransport
from yoke_harness.session_relay_cursor_acp_stderr import BoundedStderr
from yoke_harness.session_relay_cursor_cli import CursorCliTransport
from runtime.harness.session_relay_cursor_test_support import (
    ATTEMPT_ID,
    ATTESTATION,
    BOOTSTRAP,
    CHECK_INBOX,
    LAUNCH_ID,
    SESSION_ID,
    RunningProcess,
    create_request,
    local_supervision,
    native_argv,
    wake_request,
)
from yoke_harness.session_relay_runtime import RelayExecutionContext


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
    local_supervision(monkeypatch, tmp_path)

    def spawn(command, **kwargs):
        spawns.append((command, kwargs))
        return RunningProcess()

    result = CursorCliTransport(process_factory=spawn).resume_chat(
        wake_request(tmp_path)
    )

    assert result.result_code == "accepted"
    # The turn runs under the supervisor, which keeps what it says; the
    # native the supervisor was handed follows the `--` separator.
    assert result.diagnostic_ref == f"nd-{ATTEMPT_ID}"
    supervised, options = spawns[0]
    command = native_argv(supervised)
    assert command[:3] == ["/opt/cursor-agent", "--resume", SESSION_ID]
    assert "--trust" in command
    assert "--force" in command
    # The one channel cursor-agent honors: without it the turn silently runs
    # the machine default, whatever the launch asked for.
    assert command[command.index("--model") + 1] == "composer-2"
    assert command[-1] == CHECK_INBOX
    assert "CODEX_SESSION_ID" not in options["env"]
    assert options["env"]["YOKE_EXECUTOR"] == "cursor"
    assert options["env"]["YOKE_PROVIDER"] == "cursor"
    assert options["env"]["CURSOR_INVOKED_AS"] == "cursor-agent"
    # YOKE_MODEL tells the session inside which variant it was asked for;
    assert options["env"]["YOKE_MODEL"] == "composer-2"
    # A wake carries no launch, so it must not carry a launch attestation.
    assert LAUNCH_CONTEXT_ENV not in options["env"]


def test_cli_wake_names_no_model_when_the_relay_asked_for_none(
    monkeypatch,
    tmp_path: Path,
) -> None:
    # A wake inherits whatever variant the conversation last ran, so naming a
    # model the relay did not ask for would override the session's own.
    spawns = []
    monkeypatch.setattr(
        cli_module, "resolve_native_cli", lambda _name: "/opt/cursor-agent"
    )
    local_supervision(monkeypatch, tmp_path)
    request = replace(wake_request(tmp_path), requested_model=None)

    CursorCliTransport(
        process_factory=lambda command, **kwargs: (
            spawns.append((command, kwargs)) or RunningProcess()
        )
    ).resume_chat(request)

    supervised, options = spawns[0]
    command = native_argv(supervised)
    assert "--model" not in command and "YOKE_MODEL" not in options["env"]


def test_cli_wake_refuses_an_inexact_session_before_spawn(
    monkeypatch,
    tmp_path: Path,
) -> None:
    spawns = []
    monkeypatch.setattr(
        cli_module, "resolve_native_cli", lambda _name: "/opt/cursor-agent"
    )
    request = replace(wake_request(tmp_path), target_session_id="not-an-id")

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
        self.refuse_set_model = False
        self.process = SimpleNamespace(pid=4321)

    def request(self, method, params):
        self.requests.append((method, params))
        if method == "session/set_model" and self.refuse_set_model:
            raise acp_module.CursorAcpError("Invalid model value")
        if method == "session/new":
            if self.new_session_result is not None:
                return self.new_session_result
            if self.new_session_id:
                return {"sessionId": self.new_session_id}
        return {}

    def start_prompt(self, session_id, instruction, turn):
        self.prompts.append((session_id, instruction))
        self.turn = turn

    def close(self):
        self.closed = True


def test_acp_idle_wake_loads_and_prompts_the_exact_session(
    monkeypatch,
    tmp_path: Path,
) -> None:
    client = FakeAcpClient()
    transport = CursorAcpTransport(worker=True)
    monkeypatch.setattr(transport, "_client", lambda _checkout, _request: client)

    result = transport.prompt_session(wake_request(tmp_path))

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

    result = transport.new_session(create_request(tmp_path))

    assert result.result_code == "native_created"
    assert result.native_session_id == SESSION_ID
    assert client.requests == [
        ("session/new", {"cwd": str(tmp_path.resolve()), "mcpServers": []}),
        (
            "session/set_model",
            {"sessionId": SESSION_ID, "modelId": "composer-2"},
        ),
    ]
    assert client.prompts == [(SESSION_ID, BOOTSTRAP)]
    # The relay owns the process, so it records what it would have to kill.
    assert recorded == [(LAUNCH_ID, client.process.pid, SESSION_ID)]


def test_acp_launch_survives_a_refused_model_selection(
    monkeypatch,
    tmp_path: Path,
) -> None:
    # session/set_model admits only its own bracket catalog, so a launch
    # naming a command-line variant is refused there. The session still
    # launches at its default and records what it actually ran.
    client = FakeAcpClient()
    client.new_session_id = SESSION_ID
    client.refuse_set_model = True
    transport = CursorAcpTransport(worker=True)
    monkeypatch.setattr(transport, "_client", lambda _checkout, _request: client)
    monkeypatch.setattr(
        acp_module,
        "record_supervised_native",
        lambda launch_id, pid, native_session_id=None: None,
    )

    result = transport.new_session(create_request(tmp_path))

    assert result.result_code == "native_created"
    assert client.prompts == [(SESSION_ID, BOOTSTRAP)]


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

    result = transport.new_session(create_request(tmp_path))

    assert result.result_code == "not_created"
    assert result.native_session_id is None
    assert "currentModeId" in (result.identity_output_snippet or "")
    assert result.identity_parse_expectation
    assert client.closed is True
    assert client.prompts == []


def _drained(payload: bytes) -> BoundedStderr:
    drain = BoundedStderr(io.BytesIO(payload))
    for _attempt in range(200):
        if drain.tail() == payload:
            break
        time.sleep(0.01)
    return drain


def test_bounded_stderr_keeps_only_the_recent_tail() -> None:
    drain = BoundedStderr(io.BytesIO(b"abcdefghij"), limit=4)
    for _attempt in range(200):
        if drain.tail() == b"ghij":
            break
        time.sleep(0.01)
    assert drain.tail() == b"ghij"


def test_acp_launch_failure_carries_what_the_native_said(
    monkeypatch,
    tmp_path: Path,
) -> None:
    client = FakeAcpClient()
    client.new_session_result = {"models": {"currentModelId": "default[]"}}
    client.stderr = _drained(b"cursor-agent: not logged in\n")
    client.process = SimpleNamespace(pid=4321, poll=lambda: 3)
    transport = CursorAcpTransport(worker=True)
    monkeypatch.setattr(transport, "_client", lambda _checkout, _request: client)

    result = transport.new_session(create_request(tmp_path))

    assert result.result_code == "not_created"
    assert result.native_stderr == b"cursor-agent: not logged in\n"
    assert result.exit_code == 3


def test_failed_create_reaches_the_relay_as_a_private_diagnostic(
    tmp_path: Path,
) -> None:
    """Native words never ride the report wire; the relay retains them locally."""

    class FailingAcp:
        def new_session(self, request):
            return CursorNativeResult(
                "not_created",
                native_stderr=b"no conversation found with session id\n",
            )

        def prompt_session(self, request):
            raise AssertionError("launch must not prompt")

    context = RelayExecutionContext(
        job_kind="launch",
        job_id=LAUNCH_ID,
        lease_id="lease-launch",
        surface="cursor-cli",
        surface_version="2026.08.11-e8db854",
        project_id=7,
        checkout=tmp_path,
        native_instruction=BOOTSTRAP,
        launch_attestation=ATTESTATION,
    )
    result = build_cursor_adapter(
        acp_port=FailingAcp(),
        identity_lookup=lambda _conversation_id: None,
        attestation_handoff=lambda *_args, **_kwargs: True,
        sleeper=lambda _seconds: None,
    )(context)

    assert result.result_code == "not_created"
    assert result.private_diagnostic is not None
    assert result.private_diagnostic.failure_class == "no_conversation_found"
    assert result.private_diagnostic.stderr.startswith(b"no conversation found")
    # The redacted evidence the relay reports carries none of it.
    assert "no conversation" not in str(result.evidence)
