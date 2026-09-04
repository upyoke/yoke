"""Provider model-combination refusals stay named, bounded, and non-fallback."""

from __future__ import annotations

from runtime.harness.test_session_relay_claude import (
    CLAUDE,
    _allow,
    _context as claude_context,
    _started,
)
from runtime.harness.test_session_relay_codex import (
    FakeTransport,
    context as codex_context,
)
from runtime.harness.test_session_relay_cursor import (
    FakeSubprocess,
    _adapter as cursor_adapter,
    _launch as cursor_launch,
)
from yoke_harness.session_relay_claude import run_claude_cli_adapter
from yoke_harness.session_relay_codex import (
    CodexNativeOutcome,
    build_codex_relay_adapter,
)
from yoke_harness.session_relay_cursor import CursorNativeResult
from yoke_harness.session_relay_native_capture_format import compose_capture


REJECTION = "Error: model does not support effort max"


def test_claude_runtime_rejection_is_not_an_uncertain_launch(tmp_path) -> None:
    capture = tmp_path / "capture.capture"
    capture.write_bytes(
        compose_capture(stdout=b"", stderr=REJECTION.encode(), exit_code=2)
    )
    result = run_claude_cli_adapter(
        claude_context(
            requested_model="claude-opus-4-8",
            requested_reasoning_effort="max",
        ),
        create_spawner=lambda invocation: _started(invocation, capture),
        executable_finder=lambda _name: CLAUDE,
        version_gate=_allow,
    )

    assert result.result_code == "not_created"
    assert result.evidence["result_code"] == "model_combo_unsupported"
    assert result.evidence["probe_detail"] == REJECTION


def test_codex_runtime_rejection_is_not_retried_with_defaults(tmp_path) -> None:
    cli = FakeTransport(
        CodexNativeOutcome(
            "not_created",
            failure_code="model_combo_unsupported",
            failure_detail=REJECTION,
        )
    )
    adapter = build_codex_relay_adapter(
        cli_transport=cli,
        desktop_transport=FakeTransport(),
        version_gate=lambda *_args: True,
    )

    result = adapter(codex_context(tmp_path))

    assert len(cli.calls) == 1
    assert result.result_code == "not_created"
    assert result.evidence["result_code"] == "model_combo_unsupported"
    assert result.evidence["probe_detail"] == REJECTION


def test_cursor_runtime_rejection_is_not_retried_with_defaults(tmp_path) -> None:
    cli = FakeSubprocess()
    cli.new_result = CursorNativeResult(
        "not_created", exit_code=2, native_stderr=REJECTION.encode()
    )

    result = cursor_adapter(subprocess_port=cli)(cursor_launch(tmp_path))

    assert len(cli.new_requests) == 1
    assert result.result_code == "not_created"
    assert result.evidence["result_code"] == "model_combo_unsupported"
    assert result.evidence["probe_detail"] == REJECTION
