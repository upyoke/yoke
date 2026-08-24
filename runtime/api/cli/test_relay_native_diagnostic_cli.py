"""Machine-local operator retrieval for native relay diagnostics."""

from __future__ import annotations

from io import BytesIO, StringIO

from yoke_cli.commands import registry_session_control
from yoke_cli.commands.adapters import session_control_relay as relay


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

    assert relay.relay_diagnostic(["nd-" + "a" * 32]) == 0
    assert output.buffer.getvalue() == b"raw\x00error\n"


def test_relay_diagnostic_refuses_subagent_ownership(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(relay, "is_subagent_execution", lambda: True)
    called = []
    monkeypatch.setattr(relay, "_read_diagnostic", called.append)

    assert relay.relay_diagnostic(["nd-" + "a" * 32]) == 2
    assert called == []
    assert "top-level" in capsys.readouterr().err.lower()


def test_relay_diagnostic_reports_safe_unavailable_error(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(relay, "is_subagent_execution", lambda: False)

    def unavailable(_reference):
        raise RuntimeError("diagnostic has expired")

    monkeypatch.setattr(relay, "_read_diagnostic", unavailable)

    assert relay.relay_diagnostic(["nd-" + "a" * 32]) == 1
    assert "relay_diagnostic_unavailable" in capsys.readouterr().err


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
