"""Cursor create identity resolution through native hook registration."""

from __future__ import annotations

from pathlib import Path

from yoke_contracts.session_control.capabilities import native_create_timeout_seconds
from yoke_contracts.session_control.launch_bootstrap import native_launch_bootstrap
from yoke_harness.session_relay_cursor import CursorNativeResult, build_cursor_adapter
from yoke_harness.session_relay_cursor_registration import complete_bound_launch
from yoke_harness.session_relay_runtime import RelayExecutionContext


SESSION_ID = "22222222-2222-4222-8222-222222222222"
LAUNCH_ID = "33333333-3333-4333-8333-333333333333"
ATTESTATION = "secret-launch-attestation"
DIAGNOSTIC_REF = f"nd-{LAUNCH_ID}"


def _launch(tmp_path: Path, resolver=None) -> RelayExecutionContext:
    return RelayExecutionContext(
        job_kind="launch",
        job_id=LAUNCH_ID,
        lease_id="lease-launch",
        surface="cursor-cli",
        surface_version="2026.09.02-c22c1a3",
        project_id=7,
        checkout=tmp_path,
        native_instruction=native_launch_bootstrap(LAUNCH_ID),
        message_id="44444444-4444-4444-8444-444444444444",
        launch_attestation=ATTESTATION,
        launch_registration_resolver=resolver,
    )


def _spawned(tmp_path: Path) -> CursorNativeResult:
    return CursorNativeResult(
        "native_created",
        duration_ms=10,
        phase="registration_pending",
        diagnostic_ref=DIAGNOSTIC_REF,
        capture_path=str(tmp_path / "native.capture"),
        native_pid=4321,
    )


def test_cursor_uses_the_shared_supervised_create_registration_window() -> None:
    assert native_create_timeout_seconds("cursor-cli") == (
        native_create_timeout_seconds("claude-cli")
    )


def test_registered_candidate_binds_vendor_created_identity(tmp_path: Path) -> None:
    calls = []
    results = iter(
        (
            {"status": "registration_pending"},
            {"status": "registered_but_unbound", "session_id": SESSION_ID},
        )
    )

    result = complete_bound_launch(
        _launch(tmp_path, lambda workspace: calls.append(workspace) or next(results)),
        _spawned(tmp_path),
    )

    assert calls == [str(tmp_path), str(tmp_path)]
    assert result.result_code == "native_created"
    assert result.native_session_id == SESSION_ID
    assert result.evidence["result_code"] == "registered_but_unbound"
    assert result.evidence["native_launch_phase"] == "registration_pending"
    assert result.evidence["native_launch_pid"] == 4321
    assert result.evidence["native_diagnostic_ref"] == DIAGNOSTIC_REF
    assert result.evidence["native_capture_path"] == str(tmp_path / "native.capture")


def test_pending_registration_keeps_native_custody_evidence(tmp_path: Path) -> None:
    result = complete_bound_launch(
        _launch(tmp_path, lambda _workspace: {"status": "registration_pending"}),
        _spawned(tmp_path),
    )

    assert result.result_code == "outcome_unknown"
    assert result.native_session_id is None
    assert result.evidence["result_code"] == "registration_pending"
    assert result.evidence["native_launch_phase"] == "registration_pending"
    assert result.evidence["native_launch_pid"] == 4321
    assert result.evidence["native_diagnostic_ref"] == DIAGNOSTIC_REF
    assert result.evidence["native_capture_path"] == str(tmp_path / "native.capture")


def test_adapter_spawn_exception_names_the_spawn_phase(tmp_path: Path) -> None:
    class Exploding:
        def new_session(self, request):
            raise OSError("spawn refused")

        def resume_chat(self, request):
            raise AssertionError("launch must not resume")

    result = build_cursor_adapter(subprocess_port=Exploding())(_launch(tmp_path))

    assert result.result_code == "outcome_unknown"
    assert result.evidence["result_code"] == "transport_exception"
    assert result.evidence["native_launch_phase"] == "spawn"
    assert ATTESTATION not in repr(result)


def test_adapter_resolves_the_create_only_after_native_registration(
    tmp_path: Path,
) -> None:
    class NewChatTransport:
        def new_session(self, request):
            return _spawned(tmp_path)

        def resume_chat(self, request):
            raise AssertionError("launch must not resume")

    result = build_cursor_adapter(subprocess_port=NewChatTransport())(
        _launch(
            tmp_path,
            lambda _workspace: {
                "status": "registration_bound",
                "session_id": SESSION_ID,
            },
        )
    )

    assert result.result_code == "native_created"
    assert result.native_session_id == SESSION_ID
    assert result.evidence["result_code"] == "registration_bound"
