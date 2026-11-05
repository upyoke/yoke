# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from functools import partial

from itertools import count

from pathlib import Path

from types import SimpleNamespace

import pytest

from yoke_contracts.session_control.launch_bootstrap import native_launch_bootstrap

from yoke_contracts.session_control.wake_instruction import native_wake_instruction

from yoke_harness.session_relay_claude import (
    ClaudeNativeInvocation,
    run_claude_cli_adapter,
    unsupported_claude_route,
)

from yoke_harness import session_relay_claude, session_relay_native_create

from yoke_harness.session_relay_native_capture_format import compose_capture

from yoke_harness.session_relay_native_spawn import SupervisedNative

LAUNCH_ID = "12345678-1234-4234-8234-123456789abc"

BOOTSTRAP = native_launch_bootstrap(LAUNCH_ID)

MESSAGE_ID = "message-1"

CHECK_INBOX = native_wake_instruction(MESSAGE_ID)

CLAUDE = "/opt/claude/bin/claude"

CLAUDE_LOCAL_SETTINGS_JSON = '{"disableRemoteControl":true}'


def _context(**overrides):
    values = {
        "job_kind": "launch",
        "job_id": LAUNCH_ID,
        "lease_id": "lease-1",
        "surface": "claude-cli",
        "surface_version": "2.1.238",
        "project_id": 10,
        "checkout": Path("/project"),
        "native_instruction": BOOTSTRAP,
        "message_id": MESSAGE_ID,
        "target_session_id": None,
        "launch_attestation": "secret-attestation",
        "requested_model": "claude-opus-4-1",
        "presentation": "local",
        "session_name": "Session display name",
        "launch_deadline_at": "2099-08-22T12:15:00Z",
        "launch_progress_reporter": None,
        "target_liveness": None,
        "wake_mode": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _allow(surface, version, operation):
    assert surface == "claude-cli"
    assert version == "2.1.238"
    assert operation in {"create", "message_active", "message_idle", "message_stopped"}
    return True


DIAGNOSTIC_REF = "nd-33333333-3333-4333-8333-333333333333"


def _started(
    invocation: ClaudeNativeInvocation,
    capture_path: Path | None = None,
) -> SupervisedNative:
    return SupervisedNative(
        4242,
        invocation.executable,
        "path",
        capture_path or Path("/state/native-diagnostics/never-written.capture"),
        DIAGNOSTIC_REF,
        "2026-09-03T21:00:00Z",
    )
