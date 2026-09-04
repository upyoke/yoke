"""Documented Cursor CLI framing over fake native processes."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from uuid import UUID

from yoke_harness import session_relay_cursor_cli as cli_module
from yoke_harness.session_launch_handoff import LAUNCH_CONTEXT_ENV
from yoke_harness.session_relay_cursor import (
    CursorNativeResult,
    build_cursor_adapter,
)
from yoke_harness.session_relay_cursor_cli import CursorCliTransport
from yoke_harness.session_relay_native_capture_format import NativeCapture
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


def test_cli_create_starts_the_bootstrap_on_a_conversation_it_minted(
    monkeypatch,
    tmp_path: Path,
) -> None:
    spawns = []
    monkeypatch.setenv("CLAUDE_SESSION_ID", "parent-session")
    monkeypatch.setenv("YOKE_EXECUTOR", "claude-code")
    monkeypatch.setattr(
        cli_module, "resolve_native_cli", lambda _name: "/opt/cursor-agent"
    )
    local_supervision(monkeypatch, tmp_path)

    def spawn(command, **kwargs):
        spawns.append((command, kwargs))
        return RunningProcess()

    result = CursorCliTransport(process_factory=spawn).new_session(
        create_request(tmp_path)
    )

    assert result.result_code == "native_created"
    # The create names the conversation it is about to start, so the relay
    # knows which one it owns before the turn produces anything.
    minted = str(result.native_session_id)
    assert str(UUID(minted)) == minted
    supervised, options = spawns[0]
    command = native_argv(supervised)
    assert command[:3] == ["/opt/cursor-agent", "--resume", minted]
    assert "--print" in command
    assert command[command.index("--workspace") + 1] == str(tmp_path)
    assert "--trust" in command
    # Nobody is watching this terminal, so an approval prompt is a stall.
    assert "--force" in command
    assert command[command.index("--model") + 1] == "composer-2"
    assert command[-1] == BOOTSTRAP
    assert options["env"]["YOKE_EXECUTOR"] == "cursor"
    assert options["env"]["YOKE_MODEL"] == "composer-2"
    assert "CLAUDE_SESSION_ID" not in options["env"]
    # The first hook registers the session from the launch it inherits.
    assert LAUNCH_ID in options["env"][LAUNCH_CONTEXT_ENV]
    assert ATTESTATION in options["env"][LAUNCH_CONTEXT_ENV]
    assert ATTESTATION not in " ".join(command)


def test_cli_create_reports_a_native_that_refused_its_own_invocation(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        cli_module, "resolve_native_cli", lambda _name: "/opt/cursor-agent"
    )
    local_supervision(monkeypatch, tmp_path)
    monkeypatch.setattr(
        cli_module,
        "immediate_native_refusal",
        lambda _capture, **_options: NativeCapture(
            state="exited",
            stdout=b"",
            stderr=b"Error: model does not support effort max\n",
            exit_code=2,
        ),
    )

    result = CursorCliTransport(
        process_factory=lambda *_args, **_kwargs: RunningProcess()
    ).new_session(create_request(tmp_path))

    assert result.result_code == "not_created"
    assert result.exit_code == 2
    assert b"does not support effort max" in result.native_stderr


def test_cli_create_refuses_before_spawn_without_a_native(
    monkeypatch,
    tmp_path: Path,
) -> None:
    spawns = []
    monkeypatch.setattr(cli_module, "resolve_native_cli", lambda _name: None)

    result = CursorCliTransport(
        process_factory=lambda *args, **kwargs: spawns.append((args, kwargs))
    ).new_session(create_request(tmp_path))

    assert result.result_code == "not_created"
    assert spawns == []


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


def test_failed_create_reaches_the_relay_as_a_private_diagnostic(
    tmp_path: Path,
) -> None:
    """Native words never ride the report wire; the relay retains them locally."""

    class FailingTransport:
        def new_session(self, request):
            return CursorNativeResult(
                "not_created",
                native_stderr=b"no conversation found with session id\n",
            )

        def resume_chat(self, request):
            raise AssertionError("launch must not resume")

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
        subprocess_port=FailingTransport(),
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
