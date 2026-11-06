# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

from pathlib import Path

from types import SimpleNamespace

import pytest

from yoke_contracts.session_control.launch_bootstrap import native_launch_bootstrap

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

SECRET = "one-time-launch-attestation"

INSTRUCTION = native_launch_bootstrap("launch-1")


class FakeTransport:
    def __init__(self, outcome: CodexNativeOutcome | None = None) -> None:
        self.outcome = outcome or CodexNativeOutcome(
            "accepted", "native-1", identity_correlated=True
        )
        self.calls: list[tuple[str, CodexNativeRequest]] = []

    def create(self, request: CodexNativeRequest) -> CodexNativeOutcome:
        self.calls.append(("create", request))
        return self.outcome

    def wake(self, request: CodexNativeRequest) -> CodexNativeOutcome:
        self.calls.append(("wake", request))
        return self.outcome


def context(
    tmp_path: Path,
    *,
    surface: str = "codex-cli",
    job_kind: str = "launch",
    job_id: str | None = None,
    target_liveness: str | None = None,
    wake_mode: str | None = "waiting",
    target_session_id: str | None = "unset",
    target_native_thread_id: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        job_kind=job_kind,
        job_id=job_id or ("launch-1" if job_kind == "launch" else "attempt-1"),
        lease_id="lease-1",
        surface=surface,
        surface_version=(
            "0.148.0-alpha.15" if surface == "codex-cli" else "26.814.41407"
        ),
        project_id=10,
        checkout=tmp_path,
        message_id="message-1",
        native_instruction=INSTRUCTION,
        target_session_id=(
            ("native-1" if job_kind == "wake" else None)
            if target_session_id == "unset"
            else target_session_id
        ),
        target_native_thread_id=target_native_thread_id,
        launch_attestation=SECRET if job_kind == "launch" else None,
        requested_model="gpt-5.6",
        presentation="focused",
        session_name=None,
        target_liveness=target_liveness,
        wake_mode=wake_mode,
    )
