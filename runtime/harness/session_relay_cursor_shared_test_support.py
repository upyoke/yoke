# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from pathlib import Path

from types import SimpleNamespace

import pytest

from yoke_contracts.session_control.launch_bootstrap import (
    LAUNCH_BOOTSTRAP_REFUSAL,
    native_launch_bootstrap,
)

from yoke_contracts.session_control.wake_instruction import native_wake_instruction

from yoke_harness.session_relay_cursor import (
    CursorNativeResult,
    build_cursor_adapter,
    cursor_relay_adapter,
)

from yoke_harness.session_relay_runtime import RelayExecutionContext

ATTESTATION = "secret-launch-attestation"

NATIVE_ID = "44444444-4444-4444-8444-444444444444"


def _adapter(**kwargs):
    return build_cursor_adapter(**kwargs)


class FakeSubprocess:
    def __init__(self) -> None:
        self.new_requests = []
        self.resume_requests = []
        self.new_result = CursorNativeResult("native_created")
        self.resume_result = CursorNativeResult("accepted", exit_code=0, duration_ms=8)

    def new_session(self, request):
        self.new_requests.append(request)
        return self.new_result

    def resume_chat(self, request):
        self.resume_requests.append(request)
        return self.resume_result


def _launch(
    tmp_path: Path,
    *,
    surface: str = "cursor-cli",
    instruction=None,
    registration_resolver=None,
):
    launch_id = "11111111-1111-4111-8111-111111111111"
    expected = native_launch_bootstrap(launch_id)
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
        launch_registration_resolver=registration_resolver
        or (
            lambda _workspace: {
                "status": "registered_but_unbound",
                "session_id": NATIVE_ID,
            }
        ),
    )


def _wake(
    tmp_path: Path,
    *,
    surface: str = "cursor-cli",
    instruction=None,
    liveness: str = "ended",
    wake_mode: str = "waiting",
    job_id: str = "wake-attempt",
):
    message_id = "33333333-3333-4333-8333-333333333333"
    expected = native_wake_instruction(message_id)
    return RelayExecutionContext(
        job_kind="wake",
        job_id=job_id,
        lease_id="lease-wake",
        surface=surface,
        surface_version="2026.08.11-e8db854",
        project_id=7,
        checkout=tmp_path,
        native_instruction=expected if instruction is None else instruction,
        message_id=message_id,
        target_session_id="cursor-session-existing",
        target_liveness=liveness,
        wake_mode=wake_mode,
    )
