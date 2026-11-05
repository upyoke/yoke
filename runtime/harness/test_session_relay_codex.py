"""Closed Codex relay adapter, identity, version, and redaction tests."""

from __future__ import annotations

from runtime.harness.session_relay_codex_test_support import (
    FakeTransport as FakeTransport,
    INSTRUCTION as INSTRUCTION,
    SECRET as SECRET,
    context as context,
)

import json
from pathlib import Path

import pytest

from yoke_harness import session_relay_codex as adapter_module
from yoke_harness.session_relay_codex import (
    CodexNativeOutcome,
    CodexNativeRequest,
    build_codex_relay_adapter,
)
from yoke_harness.session_relay_codex_cli import LAUNCH_CONTEXT_ENV
from yoke_harness.session_relay_codex_invocation import (
    codex_base_command,
    codex_launch_environment,
)








def test_launch_uses_injected_gate_and_keeps_secret_out_of_result(
    tmp_path: Path,
) -> None:
    cli = FakeTransport()
    desktop = FakeTransport()
    gates = []
    adapter = build_codex_relay_adapter(
        cli_transport=cli,
        desktop_transport=desktop,
        version_gate=lambda *args: gates.append(args) or True,
    )

    result = adapter(context(tmp_path))

    assert gates == [("codex-cli", "0.148.0-alpha.15", "create")]
    assert result.result_code == "native_created"
    assert result.native_session_id == "native-1"
    assert cli.calls[0][1].native_instruction == INSTRUCTION
    assert cli.calls[0][1].instruction_id == "launch:launch-1"
    assert cli.calls[0][1].launch_attestation == SECRET
    assert SECRET not in repr(cli.calls[0][1])
    assert INSTRUCTION not in repr(cli.calls[0][1])
    assert SECRET not in repr(result)
    assert INSTRUCTION not in repr(result)
    assert desktop.calls == []


@pytest.mark.parametrize(
    "surface,wake_mode,liveness,operation",
    [
        ("codex-cli", "waiting", "active", "message_stopped"),
        ("codex-cli", "idle_timeout", "ended", "message_stopped"),
        ("codex-desktop", "waiting", "active", "message_stopped"),
        ("codex-desktop", "idle_timeout", "active", "message_active"),
        ("codex-desktop", "idle_timeout", "stale", "message_idle"),
        ("codex-desktop", "idle_timeout", "ended", "message_stopped"),
    ],
)
@pytest.mark.parametrize("scenario", ["claim-held-stopped", "chain-pending-stopped"])
def test_wake_mode_authorizes_and_liveness_selects_idle_timeout_primitive(
    tmp_path: Path,
    surface: str,
    wake_mode: str,
    liveness: str,
    operation: str,
    scenario: str,
) -> None:
    cli = FakeTransport()
    desktop = FakeTransport()
    gates = []
    adapter = build_codex_relay_adapter(
        cli_transport=cli,
        desktop_transport=desktop,
        version_gate=lambda *args: gates.append(args) or True,
    )

    result = adapter(
        context(
            tmp_path,
            surface=surface,
            job_kind="wake",
            job_id=scenario,
            target_liveness=liveness,
            wake_mode=wake_mode,
        )
    )

    assert gates[0][2] == operation
    assert result.result_code == "accepted"
    selected = cli if surface == "codex-cli" else desktop
    assert selected.calls[0][0] == "wake"
    assert selected.calls[0][1].target_session_id == "native-1"
    assert selected.calls[0][1].instruction_id == "message:message-1:recipient:native-1"


def test_missing_shared_context_and_rejected_version_fail_closed(
    tmp_path: Path,
) -> None:
    cli = FakeTransport()
    adapter = build_codex_relay_adapter(
        cli_transport=cli,
        desktop_transport=FakeTransport(),
        version_gate=lambda *_args: False,
    )
    incomplete = context(tmp_path)
    del incomplete.surface_version

    missing = adapter(incomplete)
    rejected = adapter(context(tmp_path))

    assert missing.result_code == "not_created"
    assert missing.evidence == {"result_code": "context_incomplete"}
    assert rejected.result_code == "not_created"
    assert rejected.evidence["result_code"] == "version_mismatch"
    assert cli.calls == []


@pytest.mark.parametrize("wake_mode", [None, "invented"])
def test_invalid_wake_mode_and_uncorrelated_identity_never_claim_success(
    tmp_path: Path,
    wake_mode: str | None,
) -> None:
    uncorrelated = FakeTransport(
        CodexNativeOutcome("accepted", "native-1", identity_correlated=False)
    )
    adapter = build_codex_relay_adapter(
        cli_transport=uncorrelated,
        desktop_transport=FakeTransport(),
        version_gate=lambda *_args: True,
    )

    launch = adapter(context(tmp_path))
    wake = adapter(context(tmp_path, job_kind="wake", wake_mode=wake_mode))

    assert (launch.result_code, launch.native_session_id) == ("outcome_unknown", None)
    assert wake.result_code == "failed"
    assert len(uncorrelated.calls) == 1


def test_transport_exception_is_bounded_and_redacted(tmp_path: Path) -> None:
    class ExplodingTransport(FakeTransport):
        def create(self, request: CodexNativeRequest) -> CodexNativeOutcome:
            raise RuntimeError(
                f"{request.native_instruction} {request.launch_attestation}"
            )

    adapter = build_codex_relay_adapter(
        cli_transport=ExplodingTransport(),
        desktop_transport=FakeTransport(),
        version_gate=lambda *_args: True,
    )

    result = adapter(context(tmp_path))

    assert result.result_code == "outcome_unknown"
    assert result.evidence["result_code"] == "transport_exception"
    assert SECRET not in repr(result)
    assert INSTRUCTION not in repr(result)


def test_cli_side_channel_never_inherits_parent_session(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("YOKE_SESSION_ID", "parent-yoke-session")
    monkeypatch.setenv("CODEX_SESSION_ID", "parent-codex-session")
    monkeypatch.setenv("CODEX_THREAD_ID", "parent-codex-thread")
    request = adapter_module._request(context(tmp_path))[0]
    env = codex_launch_environment(request)
    command = codex_base_command("/opt/codex", request) + [request.native_instruction]

    assert "YOKE_SESSION_ID" not in env
    assert "CODEX_SESSION_ID" not in env
    assert "CODEX_THREAD_ID" not in env
    assert env["YOKE_EXECUTOR"] == "codex"
    assert env["YOKE_PROVIDER"] == "openai"
    assert env["CODEX_INTERNAL_ORIGINATOR_OVERRIDE"] == "codex-cli"
    assert json.loads(env[LAUNCH_CONTEXT_ENV]) == {
        "launch_id": "launch-1",
        "attestation": SECRET,
    }
    assert SECRET not in repr(command)
    assert LAUNCH_CONTEXT_ENV not in repr(command)


# App-server wake mechanics (status transitions, turn ownership) live in
# test_session_relay_codex_app_server_wake.py. Hand-started vs. launched
# wake thread-id resolution, and the thread_id_unknown refusal, live in
# test_session_relay_codex_native_thread_id.py (350-line authored cap).
