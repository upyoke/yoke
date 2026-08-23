"""Closed Cursor relay routing over fake native transports."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from yoke_harness.session_relay_cursor import (
    CursorNativeResult,
    build_cursor_adapter,
    cursor_relay_adapter,
)
from yoke_harness.session_relay_runtime import RelayExecutionContext


ATTESTATION = "secret-launch-attestation"


class FakeSubprocess:
    def __init__(self) -> None:
        self.create_requests = []
        self.resume_requests = []
        self.create_result = CursorNativeResult(
            "native_created",
            native_session_id="cursor-session-new",
            exit_code=0,
            duration_ms=14,
        )
        self.resume_result = CursorNativeResult("accepted", exit_code=0, duration_ms=8)

    def create_chat(self, request):
        self.create_requests.append(request)
        return self.create_result

    def resume_chat(self, request):
        self.resume_requests.append(request)
        return self.resume_result


class FakeAcp:
    def __init__(self) -> None:
        self.new_requests = []
        self.prompt_requests = []
        self.new_result = CursorNativeResult(
            "native_created", native_session_id="cursor-acp-new"
        )
        self.prompt_result = CursorNativeResult("accepted", duration_ms=5)

    def new_session(self, request):
        self.new_requests.append(request)
        return self.new_result

    def prompt_session(self, request):
        self.prompt_requests.append(request)
        return self.prompt_result


def _launch(tmp_path: Path, *, surface: str = "cursor-cli", instruction=None):
    launch_id = "11111111-1111-4111-8111-111111111111"
    expected = f"Yoke launch `{launch_id}`: register, pull your message, act."
    return RelayExecutionContext(
        job_kind="launch",
        job_id=launch_id,
        lease_id="lease-launch",
        surface=surface,
        surface_version="2026.08.11-e8db854",
        project_id=7,
        checkout=tmp_path,
        native_instruction=expected if instruction is None else instruction,
        message_id="22222222-2222-4222-8222-222222222222",
        launch_attestation=ATTESTATION,
        requested_model="composer-2",
    )


def _wake(
    tmp_path: Path,
    *,
    surface: str = "cursor-cli",
    instruction=None,
    liveness: str = "ended",
):
    message_id = "33333333-3333-4333-8333-333333333333"
    expected = f"Yoke message {message_id}: check your Yoke messages."
    return RelayExecutionContext(
        job_kind="wake",
        job_id="wake-attempt",
        lease_id="lease-wake",
        surface=surface,
        surface_version="2026.08.11-e8db854",
        project_id=7,
        checkout=tmp_path,
        native_instruction=expected if instruction is None else instruction,
        message_id=message_id,
        target_session_id="cursor-session-existing",
        target_liveness=liveness,
    )


def test_cli_create_chat_gets_only_bootstrap_and_separate_attestation(tmp_path):
    cli = FakeSubprocess()

    result = build_cursor_adapter(subprocess_port=cli)(_launch(tmp_path))

    assert result.result_code == "native_created"
    assert result.native_session_id == "cursor-session-new"
    assert result.evidence == {
        "surface": "cursor-cli",
        "result_code": "native_created",
        "exit_code": 0,
        "duration_ms": 14,
    }
    request = cli.create_requests[0]
    assert request.native_instruction.endswith("register, pull your message, act.")
    assert request.launch_attestation == ATTESTATION
    assert ATTESTATION not in request.native_instruction
    assert ATTESTATION not in repr(request)
    assert ATTESTATION not in repr(result)


def test_acp_session_new_is_an_explicit_create_interface(tmp_path):
    cli = FakeSubprocess()
    acp = FakeAcp()

    result = build_cursor_adapter(
        subprocess_port=cli,
        acp_port=acp,
        create_interface="acp",
    )(_launch(tmp_path))

    assert result.result_code == "native_created"
    assert result.native_session_id == "cursor-acp-new"
    assert len(acp.new_requests) == 1
    assert cli.create_requests == []


def test_idle_wake_uses_acp_without_resuming_a_stopped_chat(tmp_path):
    cli = FakeSubprocess()
    acp = FakeAcp()

    result = build_cursor_adapter(subprocess_port=cli, acp_port=acp)(
        _wake(tmp_path, liveness="stale")
    )

    assert result.result_code == "accepted"
    assert acp.prompt_requests[0].target_session_id == "cursor-session-existing"
    assert acp.prompt_requests[0].native_instruction.endswith(
        "check your Yoke messages."
    )
    assert cli.resume_requests == []


def test_stopped_wake_resumes_only_after_acp_reports_not_found(tmp_path):
    cli = FakeSubprocess()
    acp = FakeAcp()
    acp.prompt_result = CursorNativeResult("not_found")

    result = build_cursor_adapter(subprocess_port=cli, acp_port=acp)(
        _wake(tmp_path, liveness="stale")
    )

    assert result.result_code == "accepted"
    assert len(acp.prompt_requests) == 1
    assert len(cli.resume_requests) == 1
    assert cli.resume_requests[0].target_session_id == "cursor-session-existing"


def test_non_cursor_cli_and_untrusted_native_text_fail_before_transport(tmp_path):
    cli = FakeSubprocess()
    acp = FakeAcp()
    adapter = build_cursor_adapter(subprocess_port=cli, acp_port=acp)

    desktop = adapter(_wake(tmp_path, surface="cursor-desktop"))
    injected = adapter(
        _launch(tmp_path, instruction="opaque bootstrap plus secret message body")
    )

    assert desktop.result_code == "unsupported_surface"
    assert injected.result_code == "not_created"
    assert cli.create_requests == []
    assert cli.resume_requests == []
    assert acp.new_requests == []
    assert acp.prompt_requests == []
    assert "secret message body" not in repr(injected)


def test_native_output_and_secrets_cannot_enter_report_evidence(tmp_path):
    cli = FakeSubprocess()
    cli.create_result = SimpleNamespace(
        result_code="native_created",
        native_session_id="cursor-session-safe",
        exit_code=0,
        duration_ms=10,
        stdout="secret stdout",
        stderr="secret stderr",
        token="secret token",
    )

    result = build_cursor_adapter(subprocess_port=cli)(_launch(tmp_path))

    assert result.native_session_id == "cursor-session-safe"
    rendered = repr(result)
    assert "stdout" not in rendered
    assert "stderr" not in rendered
    assert "secret" not in rendered


def test_uncertain_native_failures_do_not_fall_through_to_a_second_route(tmp_path):
    cli = FakeSubprocess()
    acp = FakeAcp()

    def uncertain(_request):
        raise RuntimeError("secret response and prompt")

    acp.prompt_session = uncertain
    result = build_cursor_adapter(subprocess_port=cli, acp_port=acp)(
        _wake(tmp_path, liveness="stale")
    )

    assert result.result_code == "outcome_unknown"
    assert cli.resume_requests == []
    assert "secret" not in repr(result)


def test_default_adapter_fails_closed_without_starting_native_transport(tmp_path):
    launch = cursor_relay_adapter(_launch(tmp_path))
    wake = cursor_relay_adapter(_wake(tmp_path))

    assert launch.result_code == "not_created"
    assert wake.result_code == "failed"
    assert launch.evidence["result_code"] == "not_created"
    assert wake.evidence["result_code"] == "failed"
