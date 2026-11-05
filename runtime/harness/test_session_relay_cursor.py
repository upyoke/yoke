"""Closed Cursor relay routing over fake native transports."""

from __future__ import annotations

from runtime.harness.session_relay_cursor_shared_test_support import (
    ATTESTATION as ATTESTATION,
    FakeSubprocess as FakeSubprocess,
    NATIVE_ID as NATIVE_ID,
    _adapter as _adapter,
    _launch as _launch,
    _wake as _wake,
)


from types import SimpleNamespace

import pytest

from yoke_contracts.session_control.launch_bootstrap import (
    LAUNCH_BOOTSTRAP_REFUSAL,
    native_launch_bootstrap,
)
from yoke_contracts.session_control.wake_instruction import native_wake_instruction
from yoke_harness.session_relay_cursor import (
    CursorNativeResult,
    cursor_relay_adapter,
)


def test_launch_without_a_native_transport_creates_no_native_at_all(tmp_path):
    result = _adapter()(_launch(tmp_path))

    assert result.result_code == "not_created"
    assert result.native_session_id is None


def test_launch_binds_the_registered_chat_and_carries_a_separate_attestation(
    tmp_path,
):
    cli = FakeSubprocess()

    result = _adapter(subprocess_port=cli)(_launch(tmp_path))

    assert result.result_code == "native_created"
    assert result.native_session_id == NATIVE_ID
    assert len(cli.new_requests) == 1
    request = cli.new_requests[0]
    assert request.native_instruction == native_launch_bootstrap(request.launch_id)
    assert request.launch_attestation == ATTESTATION
    assert ATTESTATION not in request.native_instruction
    assert ATTESTATION not in repr(request)
    assert ATTESTATION not in repr(result)


def test_bootstrap_tells_an_unregistered_native_to_stop(tmp_path):
    cli = FakeSubprocess()

    _adapter(subprocess_port=cli)(_launch(tmp_path))

    instruction = cli.new_requests[0].native_instruction
    assert LAUNCH_BOOTSTRAP_REFUSAL in instruction
    assert "take no repository" in instruction


@pytest.mark.parametrize(
    ("liveness", "wake_mode"),
    [("stale", "idle_timeout"), ("active", "waiting")],
)
def test_every_wake_resumes_the_conversation_at_its_exact_id(
    tmp_path, liveness, wake_mode
):
    cli = FakeSubprocess()

    result = _adapter(subprocess_port=cli)(
        _wake(tmp_path, liveness=liveness, wake_mode=wake_mode)
    )

    assert result.result_code == "accepted"
    assert len(cli.resume_requests) == 1
    assert cli.resume_requests[0].target_session_id == "cursor-session-existing"
    assert cli.resume_requests[0].native_instruction == native_wake_instruction(
        "33333333-3333-4333-8333-333333333333"
    )


def test_a_wake_the_conversation_cannot_answer_refuses_by_name(tmp_path):
    cli = FakeSubprocess()
    cli.resume_result = CursorNativeResult("not_found")

    result = _adapter(subprocess_port=cli)(
        _wake(tmp_path, liveness="stale", wake_mode="idle_timeout")
    )

    assert result.result_code == "not_found"
    assert len(cli.resume_requests) == 1


@pytest.mark.parametrize("wake_mode", [None, "invented"])
def test_invalid_wake_mode_fails_before_native_transport(tmp_path, wake_mode):
    cli = FakeSubprocess()

    result = _adapter(subprocess_port=cli)(
        _wake(tmp_path, liveness="active", wake_mode=wake_mode)
    )

    assert result.result_code == "failed"
    assert cli.resume_requests == []


def test_non_cursor_cli_and_untrusted_native_text_fail_before_transport(tmp_path):
    cli = FakeSubprocess()
    adapter = _adapter(subprocess_port=cli)

    desktop = adapter(_wake(tmp_path, surface="cursor-desktop"))
    injected = adapter(
        _launch(tmp_path, instruction="opaque bootstrap plus secret message body")
    )

    assert desktop.result_code == "unsupported_surface"
    assert injected.result_code == "not_created"
    assert cli.resume_requests == []
    assert cli.new_requests == []
    assert "secret message body" not in repr(injected)


def test_native_output_and_secrets_cannot_enter_report_evidence(tmp_path):
    cli = FakeSubprocess()
    cli.new_result = SimpleNamespace(
        result_code="native_created",
        native_session_id=None,
        exit_code=0,
        duration_ms=10,
        stdout="secret stdout",
        stderr="secret stderr",
        token="secret token",
    )

    result = _adapter(subprocess_port=cli)(_launch(tmp_path))

    assert result.native_session_id == NATIVE_ID
    rendered = repr(result)
    assert "stdout" not in rendered
    assert "stderr" not in rendered
    assert "secret" not in rendered


def test_uncertain_native_failures_do_not_fall_through_to_a_second_route(tmp_path):
    cli = FakeSubprocess()

    def uncertain(_request):
        raise RuntimeError("secret response and prompt")

    cli.resume_chat = uncertain
    result = _adapter(subprocess_port=cli)(
        _wake(tmp_path, liveness="stale", wake_mode="idle_timeout")
    )

    assert result.result_code == "outcome_unknown"
    assert "secret" not in repr(result)


def test_default_adapter_fails_closed_without_starting_native_transport(tmp_path):
    launch = cursor_relay_adapter(_launch(tmp_path))
    wake = cursor_relay_adapter(_wake(tmp_path))

    assert launch.result_code == "not_created"
    assert wake.result_code == "failed"
    assert launch.evidence["result_code"] == "not_created"
    assert wake.evidence["result_code"] == "failed"
