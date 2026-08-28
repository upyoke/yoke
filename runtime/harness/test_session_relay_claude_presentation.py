"""Per-launch Claude Remote Control policy tests."""

from __future__ import annotations

from pathlib import Path

from runtime.harness.test_session_relay_claude import CLAUDE_LOCAL_SETTINGS_JSON
from yoke_harness.session_relay_claude_native import ClaudeNativeInvocation


def _resume(presentation):
    return ClaudeNativeInvocation(
        "/opt/claude/bin/claude",
        Path("/project"),
        "12345678-1234-4234-8234-123456789abc",
        "2.1.238",
        "Check the Yoke inbox.",
        resume=True,
        presentation=presentation,
    )


def test_managed_resume_disables_remote_control_for_this_invocation_only():
    argv = _resume("local").argv
    assert argv[argv.index("--settings") + 1] == CLAUDE_LOCAL_SETTINGS_JSON


def test_operator_opened_resume_keeps_remote_control_behavior_unchanged():
    argv = _resume(None).argv
    assert "--settings" not in argv
    assert "disableRemoteControl" not in " ".join(argv)
