"""Readable identity correlation in session-launch CLI output."""

from __future__ import annotations

import io

from yoke_cli.commands.adapters.session_control_launch_output import (
    write_launch_result,
)


def _launch(**overrides):
    result = {
        "launch_id": "launch-1",
        "project_id": 1,
        "state": "completed",
        "result_code": "native_created",
        "requested_surface": "codex-desktop",
        "selected_surface": "codex-desktop",
        "native_session_id": "session-1",
        "registered_session_id": "session-1",
        "identity_correlation": "matched",
        "instruction_delivery": "delivered",
        "result_evidence": {
            "adapter_revision": "adapter-v2",
            "native_instruction_sha256": "sha256:safe-digest",
            "result_code": "native_created",
            "surface": "codex-desktop",
            "duration_ms": 11,
            "exit_code": 0,
            "machine_id": "machine-1",
            "relay_id": "machine:machine-1",
            "native_diagnostic_ref": "nd-aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            "native_diagnostic_command": ("yoke relay diagnostic nd-aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
            "token": "secret-token",
            "body": "secret-body",
            "argv": ["secret-argument"],
            "stdout": "secret-stdout",
            "stderr": "secret-stderr",
        },
        "created_at": "2026-08-23T12:00:00Z",
        "deadline_at": "2026-08-23T12:05:00Z",
        "origin": "operator",
        "attestation_hash": "secret-attestation",
        "message_id": "secret-message",
        "requester_session_id": "secret-requester",
    }
    result.update(overrides)
    return result


def test_launch_detail_shows_identity_chain_and_only_sanitized_evidence() -> None:
    output = io.StringIO()

    write_launch_result({"launch": _launch()}, output)

    rendered = output.getvalue()
    assert "Native session" in rendered and "session-1" in rendered
    assert "Registered session" in rendered
    assert "Identity correlation" in rendered and "matched" in rendered
    assert "Origin" in rendered and "operator" in rendered
    assert "Instruction delivery" in rendered and "delivered" in rendered
    assert "Result evidence" in rendered
    assert "adapter revision=adapter-v2" in rendered
    assert "native instruction sha256=sha256:safe-digest" in rendered
    assert "result code=native_created" in rendered
    assert "surface=codex-desktop" in rendered
    assert "duration ms=11" in rendered
    assert "exit code=0" in rendered
    assert "Native diagnostic" in rendered
    assert "nd-aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa" in rendered
    assert "Diagnostic location" in rendered
    assert "machine-1 / machine:machine-1" in rendered
    assert "Retrieve diagnostic" in rendered
    assert "yoke relay diagnostic nd-aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa" in rendered
    assert "secret-attestation" not in rendered
    assert "secret-message" not in rendered
    assert "secret-requester" not in rendered
    for secret in (
        "secret-token",
        "secret-body",
        "secret-argument",
        "secret-stdout",
        "secret-stderr",
    ):
        assert secret not in rendered


def test_launch_list_distinguishes_mismatch_and_awaiting_registration() -> None:
    output = io.StringIO()

    write_launch_result(
        {
            "launches": [
                _launch(
                    native_session_id="native-a",
                    registered_session_id="registered-b",
                    identity_correlation="mismatch",
                    origin="operator",
                ),
                _launch(
                    launch_id="launch-2",
                    state="awaiting_registration",
                    native_session_id="native-c",
                    registered_session_id=None,
                    identity_correlation="awaiting_registration",
                    instruction_delivery="pending",
                    origin="steering",
                ),
            ]
        },
        output,
    )

    rendered = output.getvalue()
    assert "NATIVE" in rendered
    assert "REGISTERED" in rendered
    assert "ORIGIN" in rendered
    assert "operator" in rendered
    assert "steering" in rendered
    assert "CORRELATION" in rendered
    assert "mismatch" in rendered
    assert "awaiting registration" in rendered


def test_failed_correlation_says_instruction_was_not_delivered_and_teaches_recovery() -> (
    None
):
    output = io.StringIO()

    write_launch_result(
        {
            "launch": _launch(
                launch_id="launch-failed",
                state="outcome_unknown",
                result_code="identity_listing_lagged",
                native_session_id=None,
                registered_session_id=None,
                identity_correlation="correlation_failed",
                instruction_delivery="not_delivered",
            )
        },
        output,
    )

    rendered = output.getvalue()
    assert "failed (identity listing lagged)" in rendered
    assert "Instruction delivery" in rendered and "not delivered" in rendered
    assert "Find the native session ID" in rendered
    assert (
        "yoke session-control launch reconcile launch-failed --observed-native-id ID"
        in rendered
    )


def test_raw_evidence_string_is_never_echoed() -> None:
    output = io.StringIO()

    write_launch_result(
        {"launch": _launch(result_evidence="raw stdout and secret argv")}, output
    )

    assert "raw stdout" not in output.getvalue()
    assert "secret argv" not in output.getvalue()
