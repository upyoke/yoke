"""Machine-local operator retrieval for native relay diagnostics."""

from __future__ import annotations

from io import BytesIO, StringIO

from yoke_cli.commands import registry_session_control
from yoke_cli.commands.adapters import session_control_relay as relay
from yoke_cli.commands.adapters.session_control_human_output import (
    write_message_result,
)
from yoke_harness.session_relay import ServeOnceJobOutcome, ServeOnceOutcome


class _BinaryStdout(StringIO):
    def __init__(self) -> None:
        super().__init__()
        self.buffer = BytesIO()


def test_relay_diagnostic_emits_exact_private_capture_to_operator(
    monkeypatch,
) -> None:
    output = _BinaryStdout()
    monkeypatch.setattr(relay, "is_subagent_execution", lambda: False)
    monkeypatch.setattr(relay, "_read_diagnostic", lambda _reference: b"raw\x00error")
    monkeypatch.setattr(relay.sys, "stdout", output)

    assert relay.relay_diagnostic(["nd-aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"]) == 0
    assert output.buffer.getvalue() == b"raw\x00error\n"


def test_relay_diagnostic_allows_same_machine_user_read_from_subagent_context(
    monkeypatch,
) -> None:
    output = _BinaryStdout()
    monkeypatch.setattr(relay, "is_subagent_execution", lambda: True)
    monkeypatch.setattr(relay, "_read_diagnostic", lambda _reference: b"details")
    monkeypatch.setattr(relay.sys, "stdout", output)

    assert relay.relay_diagnostic(["nd-aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"]) == 0
    assert output.buffer.getvalue() == b"details\n"


def test_relay_serve_once_treats_reported_native_failure_as_settled(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(relay, "is_subagent_execution", lambda: False)
    monkeypatch.setattr(
        relay,
        "_serve_once",
        lambda **_kwargs: ServeOnceOutcome(
            "reported",
            jobs=(
                ServeOnceJobOutcome(
                    "reported",
                    result_code="failed",
                    diagnostic_availability="unavailable",
                    native_error_class="process_exit",
                    native_error_step="resume",
                    machine_id="machine-1",
                    relay_id="machine:machine-1",
                ),
            ),
        ),
    )

    assert relay.relay_serve_once([]) == 0
    rendered = capsys.readouterr().out
    assert "Native failure" in rendered and "process_exit" in rendered
    assert "local detail unavailable" in rendered


def test_relay_serve_once_exits_nonzero_for_build_refusal(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(relay, "is_subagent_execution", lambda: False)
    monkeypatch.setattr(
        relay,
        "_serve_once",
        lambda **_kwargs: ServeOnceOutcome(
            "relay_newer_than_server",
            error_code="relay_newer_than_server",
            error_detail=(
                "relay_newer_than_server: relay revision aaaaaaaaaaaa is newer "
                "than server revision v0.1.1+launch.365; recovery: deploy"
            ),
            local_revision="aaaaaaaaaaaa",
            server_revision="v0.1.1+launch.365",
            recovery="deploy",
        ),
    )

    assert relay.relay_serve_once(["--json"]) == 1
    payload = capsys.readouterr().out
    assert "relay_newer_than_server" in payload
    assert "v0.1.1+launch.365" in payload


def test_relay_diagnostic_reports_safe_unavailable_error(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(relay, "is_subagent_execution", lambda: False)

    def unavailable(_reference):
        raise RuntimeError("diagnostic has expired")

    monkeypatch.setattr(relay, "_read_diagnostic", unavailable)

    assert relay.relay_diagnostic(["nd-aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"]) == 1
    assert "relay_diagnostic_unavailable" in capsys.readouterr().err


def test_relay_poll_human_output_names_location_and_retrieval_recipe() -> None:
    output = StringIO()
    reference = "nd-aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"

    relay.write_relay_summary(
        {
            "state": "report_failed",
            "jobs": [
                {
                    "job_kind": "wake",
                    "job_id": "attempt-1",
                    "result_code": "native_exit",
                    "error_code": "control_plane_unreachable",
                    "relay_id": "machine:machine-1",
                    "machine_id": "machine-1",
                    "native_diagnostic_ref": reference,
                    "native_diagnostic_command": (f"yoke relay diagnostic {reference}"),
                }
            ],
        },
        output,
        title="RELAY POLL",
    )

    rendered = output.getvalue()
    assert "Native diagnostic" in rendered and reference in rendered
    assert "machine-1 / machine:machine-1" in rendered
    assert f"yoke relay diagnostic {reference}" in rendered


def test_relay_poll_human_output_keeps_typed_failure_when_capture_unavailable() -> None:
    output = StringIO()
    relay.write_relay_summary(
        {
            "state": "reported",
            "jobs": [
                {
                    "job_kind": "wake",
                    "result_code": "failed",
                    "relay_id": "machine:machine-1",
                    "machine_id": "machine-1",
                    "diagnostic_availability": "unavailable",
                    "native_error_class": "process_exit",
                    "native_error_step": "session_lookup",
                }
            ],
        },
        output,
        title="RELAY POLL",
    )

    rendered = output.getvalue()
    assert "Native failure" in rendered and "process_exit" in rendered
    assert "session_lookup" in rendered
    assert "machine-1 / machine:machine-1" in rendered
    assert "local detail unavailable" in rendered


def test_message_attempt_output_names_diagnostic_without_raw_stderr() -> None:
    output = StringIO()
    reference = "nd-bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    write_message_result(
        {
            "message": {
                "message_id": "message-1",
                "recipients": [{"session_id": "session-1", "state": "pending"}],
                "attempts": [
                    {
                        "attempt_id": "attempt-1",
                        "target_session_id": "session-1",
                        "attempt_kind": "wake",
                        "result_code": "native_exit",
                        "evidence": {
                            "native_diagnostic_ref": reference,
                            "machine_id": "machine-1",
                            "relay_id": "machine:machine-1",
                            "stderr": "never show raw stderr",
                        },
                    }
                ],
            }
        },
        output,
    )

    rendered = output.getvalue()
    assert "DELIVERY ATTEMPTS" in rendered
    assert "NATIVE DIAGNOSTIC" in rendered and reference in rendered
    assert "machine-1 / machine:machine-1" in rendered
    assert f"yoke relay diagnostic {reference}" in rendered
    assert "never show raw stderr" not in rendered


def test_relay_diagnostic_is_registered_as_a_machine_local_tool() -> None:
    route = registry_session_control.SESSION_CONTROL_TOOL_SHAPED_SUBCOMMANDS[
        ("relay", "diagnostic")
    ]

    assert route is relay.relay_diagnostic
    assert (
        registry_session_control.SESSION_CONTROL_TOOL_SHAPED_USAGE[
            "yoke relay diagnostic"
        ]
        == relay.RELAY_DIAGNOSTIC_USAGE
    )


def test_a_failed_attempt_names_its_reason_rather_than_an_empty_column() -> None:
    """`failed` with nothing beside it is the shape that hid a dead relay.

    The stored code is coarse; the adapter's own refusal is in the evidence.
    For two hours every wake on one machine refused for one nameable reason
    while the operator-facing table showed `failed` against an empty column.
    """
    output = StringIO()

    write_message_result(
        {
            "message": {
                "message_id": "message-1",
                "recipients": [{"session_id": "session-1", "state": "pending"}],
                "attempts": [
                    {
                        "attempt_id": "attempt-1",
                        "target_session_id": "session-1",
                        "attempt_kind": "wake_relay",
                        "result_code": "failed",
                        "evidence": {"result_code": "instruction_invalid"},
                    },
                    {
                        "attempt_id": "attempt-2",
                        "target_session_id": "session-1",
                        "attempt_kind": "wake_relay",
                        "result_code": "failed",
                        "evidence": {},
                    },
                    {
                        "attempt_id": "attempt-3",
                        "target_session_id": "session-1",
                        "attempt_kind": "hook",
                        "result_code": "injected",
                        "evidence": {"hook_event": "PreToolUse"},
                    },
                ],
            }
        },
        output,
    )

    lines = {
        line.split()[0]: line
        for line in output.getvalue().splitlines()
        if line.startswith("attempt-")
    }
    assert "instruction_invalid" in lines["attempt-1"]
    assert "unreported" in lines["attempt-2"]
    # A delivered hook injection is not a failure and owes no reason.
    assert "unreported" not in lines["attempt-3"]
