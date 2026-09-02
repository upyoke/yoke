"""GUI-session command routing and diagnostic coverage for macOS host control."""

from __future__ import annotations

import base64
import subprocess
from types import SimpleNamespace

import pytest

from yoke_contracts.machine_qa_execution import (
    GUI_SESSION_CONTEXT,
    REQUIRED_SESSION_CONTEXT_FIELD,
)
from yoke_core.domain.machine_qa_method_contracts import (
    MachineQaExecutionError,
    validate_machine_method_config,
)
from yoke_harness import ssh_mac_gui_session, ssh_mac_transport
from yoke_harness.ssh_mac_gui_session import (
    GUI_SESSION_UNAVAILABLE_REASON,
    run_terminal_app_command,
)
from yoke_harness.ssh_mac_transport import SshMacTransport


def _completed(
    command: str | tuple[str, ...],
    *,
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(command, returncode, stdout, stderr)


def test_terminal_app_command_returns_output_and_exit_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[str] = []

    def run(command: str, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        if "return id of targetWindow" in command:
            return _completed(command, stdout="445")
        if command.startswith("if /bin/test -f "):
            return _completed(command, stdout="7\n")
        if command.startswith("/usr/bin/base64 < "):
            value = "visible output\n" if command.endswith(".stdout") else "warning\n"
            return _completed(
                command,
                stdout=base64.b64encode(value.encode()).decode(),
            )
        return _completed(command)

    monkeypatch.setattr(
        ssh_mac_gui_session,
        "uuid4",
        lambda: SimpleNamespace(hex="c" * 32),
    )

    result = run_terminal_app_command(
        run,
        argv=("/usr/bin/printf", "%s", "hello world"),
    )

    assert result.args == ("/usr/bin/printf", "%s", "hello world")
    assert result.returncode == 7
    assert result.stdout == "visible output\n"
    assert result.stderr == "warning\n"
    launch = next(command for command in commands if "set targetTab" in command)
    assert "/usr/bin/printf" in launch
    assert "hello world" in launch
    assert "yoke-gui-session-cccccccccccc.exit" in launch
    assert any(command.startswith("/bin/rm -f ") for command in commands)
    assert any("close window id 445" in command for command in commands)


def test_machine_assertion_declares_gui_session_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ssh_commands: list[str] = []
    gui_argv: list[tuple[str, ...]] = []

    def run(command: str, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        ssh_commands.append(command)
        return _completed(command)

    def run_gui(
        _run: object,
        *,
        argv: tuple[str, ...],
        timeout: int = 60,
    ) -> subprocess.CompletedProcess[str]:
        assert timeout == 60
        gui_argv.append(tuple(argv))
        return _completed(tuple(argv), stdout="captured")

    monkeypatch.setattr(ssh_mac_transport, "run_terminal_app_command", run_gui)
    control = SshMacTransport.__new__(SshMacTransport)
    control._run = run

    result = control.run_machine_assertions(
        [
            {
                "argv": ["/usr/sbin/screencapture", "-x", "/tmp/proof.png"],
                REQUIRED_SESSION_CONTEXT_FIELD: GUI_SESSION_CONTEXT,
            }
        ]
    )

    assert result.ok is True
    assert gui_argv == [("/usr/sbin/screencapture", "-x", "/tmp/proof.png")]
    assert ssh_commands == []
    assert result.evidence["assertions"][0]["execution_context"] == "gui"
    assert (
        result.evidence["assertions"][0][REQUIRED_SESSION_CONTEXT_FIELD]
        == GUI_SESSION_CONTEXT
    )


def test_transport_exposes_gui_session_command_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def run_gui(
        _run: object,
        *,
        argv: tuple[str, ...],
        timeout: int = 60,
    ) -> subprocess.CompletedProcess[str]:
        return _completed(tuple(argv), returncode=9, stdout="gui output")

    monkeypatch.setattr(ssh_mac_transport, "run_terminal_app_command", run_gui)
    control = SshMacTransport.__new__(SshMacTransport)
    control._run = lambda command, **_kwargs: _completed(command)

    result = control.run_command(
        ["/usr/bin/printf", "gui output"],
        required_session_context=GUI_SESSION_CONTEXT,
    )

    assert result.returncode == 9
    assert result.stdout == "gui output"


@pytest.mark.parametrize(
    ("stderr", "error_code", "reason"),
    [
        (
            "could not create image from display",
            "macos_window_server_context_unavailable",
            "macOS window-server context is unavailable to this process",
        ),
        (
            "Could not switch to audit session: Operation not permitted",
            "macos_gui_audit_session_unavailable",
            "macOS GUI audit-session context is unavailable to this process",
        ),
        (
            "OAuth session expired and unrefreshable",
            "macos_login_keychain_context_unavailable",
            "macOS login-keychain context is unavailable to this process",
        ),
    ],
)
def test_plain_ssh_failure_has_named_session_context_reason(
    stderr: str,
    error_code: str,
    reason: str,
) -> None:
    control = SshMacTransport.__new__(SshMacTransport)
    control._run = lambda command, **_kwargs: _completed(
        command,
        returncode=1,
        stderr=stderr,
    )

    result = control.run_machine_assertions(
        [{"argv": ["/usr/sbin/screencapture", "/tmp/proof.png"]}]
    )

    assert result.ok is False
    assert result.error_code == error_code
    assert result.evidence["session_context_degraded_reason"] == reason
    assert result.evidence["assertions"][0]["execution_context"] == "ssh"


def test_declared_context_bridge_failure_never_matches_expected_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable(
        _run: object,
        *,
        argv: tuple[str, ...],
        timeout: int = 60,
    ) -> subprocess.CompletedProcess[str]:
        return _completed(
            tuple(argv),
            returncode=125,
            stderr=f"{GUI_SESSION_UNAVAILABLE_REASON}: launch failed",
        )

    monkeypatch.setattr(
        ssh_mac_transport,
        "run_terminal_app_command",
        unavailable,
    )
    control = SshMacTransport.__new__(SshMacTransport)
    control._run = lambda command, **_kwargs: _completed(command)

    result = control.run_machine_assertions(
        [
            {
                "argv": ["/usr/bin/security", "find-generic-password"],
                "expected_exit": 125,
                REQUIRED_SESSION_CONTEXT_FIELD: GUI_SESSION_CONTEXT,
            }
        ]
    )

    assert result.ok is False
    assert result.error_code == "macos_gui_session_context_unavailable"
    assert (
        result.evidence["session_context_degraded_reason"]
        == GUI_SESSION_UNAVAILABLE_REASON
    )


def test_machine_assertion_contract_accepts_only_gui_session_context() -> None:
    normalized = validate_machine_method_config(
        "machine-state-check",
        {
            "assertions": [
                {
                    "argv": ["/usr/bin/security", "find-generic-password"],
                    REQUIRED_SESSION_CONTEXT_FIELD: GUI_SESSION_CONTEXT,
                }
            ]
        },
        entry_surface=None,
        required_completion=None,
    )
    assert (
        normalized["assertions"][0][REQUIRED_SESSION_CONTEXT_FIELD]
        == GUI_SESSION_CONTEXT
    )
    with pytest.raises(MachineQaExecutionError, match="must be 'gui'"):
        validate_machine_method_config(
            "machine-state-check",
            {
                "assertions": [
                    {
                        "argv": ["/usr/bin/true"],
                        REQUIRED_SESSION_CONTEXT_FIELD: "ssh",
                    }
                ]
            },
            entry_surface=None,
            required_completion=None,
        )
