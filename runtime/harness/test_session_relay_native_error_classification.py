"""Closed native error classification without durable stderr leakage."""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.harness.test_session_relay_claude import (
    ACTUAL_ID,
    CHECK_INBOX,
    CLAUDE,
    _allow,
    _context,
)
from yoke_contracts.session_control.evidence import redacted_evidence_document
from yoke_harness import session_relay
from yoke_harness.session_relay_claude import (
    ClaudeProcessResult,
    run_claude_cli_adapter,
)
from yoke_harness.session_relay_native_diagnostics import classify_native_failure


@pytest.mark.parametrize(
    ("stderr", "expected"),
    [
        (
            b"No conversation found with session ID: private-uuid",
            "no_conversation_found",
        ),
        (b"Session is already in use by another process", "background_session_in_use"),
        (b"unknown private native failure", "process_exit"),
    ],
)
def test_classifier_emits_only_closed_non_secret_classes(stderr, expected) -> None:
    assert classify_native_failure(stderr) == expected


def test_claude_failure_class_and_reference_are_safe_durable_evidence(
    tmp_path: Path,
) -> None:
    private_uuid = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
    stderr = f"No conversation found with session ID: {private_uuid}"
    result = run_claude_cli_adapter(
        _context(
            job_kind="wake",
            native_instruction=CHECK_INBOX,
            target_session_id=ACTUAL_ID,
            launch_attestation=None,
            target_liveness="active",
            wake_mode="waiting",
        ),
        process_runner=lambda _invocation: ClaudeProcessResult(
            1,
            10,
            stdout="private body",
            stderr=stderr,
        ),
        executable_finder=lambda _name: CLAUDE,
        version_gate=_allow,
    )

    retained = session_relay._retain_private_diagnostic(result, state_dir=tmp_path)
    durable = redacted_evidence_document(retained.evidence)

    assert durable["native_error_class"] == "no_conversation_found"
    assert durable["native_error_step"] == "resume"
    assert durable["diagnostic_availability"] == "relay_local"
    assert durable["native_diagnostic_ref"].startswith("nd-")
    assert private_uuid not in repr(durable)
    assert stderr not in repr(durable)
    assert "private body" not in repr(durable)
    assert retained.private_diagnostic is None
