"""Closed native error classification, and what of stderr is allowed to travel.

Exactly one bounded line does: the last thing the native said, because the
capture holding the rest is readable only on the machine that produced it and
a seat reading a fleet row elsewhere would otherwise have no reason at all.
Everything before that line stays local.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.harness.test_session_relay_claude import (
    CLAUDE,
    _allow,
    _context,
)
from yoke_contracts.session_control.evidence import (
    native_diagnostic_command,
    redacted_evidence_document,
)
from yoke_harness.session_relay_diagnostic_retention import (
    retain_private_diagnostic,
)
from yoke_harness.session_relay_claude import run_claude_cli_adapter
from yoke_harness.session_relay_native_capture_format import compose_capture
from yoke_harness.session_relay_native_diagnostics import classify_native_failure
from yoke_harness.session_relay_native_spawn import SupervisedNative


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


def test_claude_failure_evidence_carries_the_last_line_and_nothing_before_it(
    tmp_path: Path,
) -> None:
    private_uuid = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
    earlier = f"resolved workspace for {private_uuid}"
    diagnosis = "No conversation found with session ID"
    capture = tmp_path / "refusal.capture"
    capture.write_bytes(
        compose_capture(
            stdout=b"private body",
            stderr=f"{earlier}\n{diagnosis}".encode(),
            exit_code=1,
        )
    )
    result = run_claude_cli_adapter(
        _context(),
        create_spawner=lambda invocation: SupervisedNative(
            4242,
            invocation.executable,
            "path",
            capture,
            "nd-11111111-1111-4111-8111-111111111111",
            "2026-09-03T21:00:00Z",
        ),
        executable_finder=lambda _name: CLAUDE,
        version_gate=_allow,
    )

    retained = retain_private_diagnostic(
        result,
        attempt_id="11111111-1111-4111-8111-111111111111",
        state_dir=tmp_path,
    )
    durable = redacted_evidence_document(retained.evidence)

    assert durable["native_error_class"] == "no_conversation_found"
    assert durable["native_error_step"] == "launch"
    assert durable["diagnostic_availability"] == "relay_local"
    assert durable["native_diagnostic_ref"].startswith("nd-")
    assert durable["native_diagnostic_command"] == (
        f"yoke relay diagnostic {durable['native_diagnostic_ref']}"
    )
    assert durable["native_stderr_tail"] == diagnosis
    assert private_uuid not in repr(durable)
    assert earlier not in repr(durable)
    assert "private body" not in repr(durable)
    assert retained.private_diagnostic is None


def test_malicious_diagnostic_reference_never_becomes_a_copyable_command() -> None:
    malicious = "nd-11111111-1111-4111-8111-111111111111; open /tmp/private"

    durable = redacted_evidence_document(
        {
            "native_diagnostic_ref": malicious,
            "native_diagnostic_command": f"yoke relay diagnostic {malicious}",
            "native_error_class": "process_exit",
        }
    )

    assert durable == {"native_error_class": "process_exit"}
    with pytest.raises(ValueError, match="reference is invalid"):
        native_diagnostic_command(malicious)
