"""Native screen backend coverage for SSH macOS host control."""

from __future__ import annotations

from pathlib import Path
import shlex
import subprocess
from types import SimpleNamespace

import pytest

from yoke_harness import ssh_mac_terminal_app
from yoke_harness.ssh_mac_terminal_capture import detect_terminal_backend
from yoke_core.domain import ssh_mac_host_control
from yoke_core.domain import ssh_mac_terminal_legacy
from yoke_core.domain.ssh_mac_host_control import SshMacHostControl


_BACKEND_PROBE = (
    "if command -v tmux >/dev/null 2>&1; then printf tmux; "
    "elif command -v screen >/dev/null 2>&1; then printf screen; fi"
)


def _completed(
    command: str,
    *,
    stdout: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=command,
        returncode=0,
        stdout=stdout,
        stderr="",
    )


def test_detect_terminal_backend_selects_screen_after_tmux_probe() -> None:
    commands: list[str] = []

    def run(
        command: str,
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return _completed(command, stdout="screen\n")

    assert detect_terminal_backend(run) == "screen"
    assert commands == [_BACKEND_PROBE]


def test_check_terminal_bridge_reports_direct_terminal_app_control(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[str] = []
    transcript_reads = 0

    def run(
        command: str,
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal transcript_reads
        commands.append(command)
        if "return id of targetWindow" in command:
            return _completed(command, stdout="445")
        if "return contents of selected tab" in command:
            transcript_reads += 1
            return _completed(
                command,
                stdout=(
                    "terminal-app-ready\n"
                    if transcript_reads == 1
                    else "received-bbbbbbbbbbbb\n"
                ),
            )
        if 'tell application "System Events"' in command:
            return _completed(command, stdout="true")
        if "set shotCmd" in command:
            return _completed(command, stdout="446")
        if command.startswith("/bin/test -s "):
            return _completed(command, stdout="cG5n")
        return _completed(command)

    monkeypatch.setattr(
        ssh_mac_terminal_app,
        "uuid4",
        lambda: SimpleNamespace(hex="b" * 32),
    )
    control = SshMacHostControl.__new__(SshMacHostControl)
    control._run = run

    result = control.check_terminal_bridge()

    assert result.ok is True
    assert result.error_code is None
    assert result.evidence == {
        "terminal_backend": "Terminal.app",
        "terminal_app_launch": True,
        "terminal_app_input": True,
        "terminal_app_transcript": True,
        "terminal_app_screenshot": True,
    }
    assert not any(command == _BACKEND_PROBE for command in commands)
    launch = next(command for command in commands if "set targetTab" in command)
    assert "set bounds of targetWindow" in launch
    assert "do script" in launch
    native_input = next(
        command for command in commands if 'tell application "System Events"' in command
    )
    assert "key code 36" in native_input
    assert commands.index(native_input) > next(
        index
        for index, command in enumerate(commands)
        if "return contents of selected tab" in command
    )
    assert transcript_reads == 2
    terminal_capture = next(
        command
        for command in commands
        if "/usr/bin/osascript" in command and "/usr/sbin/screencapture" in command
    )
    assert 'tell application "Terminal"' in terminal_capture
    assert "/usr/sbin/screencapture -x -R" in terminal_capture
    assert not any(
        command.startswith("/usr/sbin/screencapture") for command in commands
    )
    assert any("close window id 445" in command for command in commands)
    assert any("close window id 446" in command for command in commands)


def test_terminal_case_uses_screen_input_hardcopy_and_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = "yoke-qa-" + "a" * 12
    expected = "Review ready"
    sent = "confirm 'yes'"
    commands: list[str] = []

    def run(
        command: str,
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        if command == _BACKEND_PROBE:
            return _completed(command, stdout="screen")
        if "return id of front window" in command:
            return _completed(command, stdout="445")
        if " hardcopy -h " in command:
            return _completed(command, stdout=f"setup\n{expected}\n")
        return _completed(command)

    monkeypatch.setattr(
        ssh_mac_terminal_legacy,
        "uuid4",
        lambda: SimpleNamespace(hex="a" * 32),
    )
    monkeypatch.setattr(
        ssh_mac_host_control.machine_config,
        "yoke_home",
        lambda: tmp_path,
    )
    control = SshMacHostControl.__new__(SshMacHostControl)
    control._run = run

    result = control.run_terminal_case(
        entry_surface="/usr/local/bin/yoke onboard --project yoke",
        required_completion="review",
        steps=[
            {
                "key": "review",
                "send": sent,
                "expect": expected,
                "timeout_seconds": 1,
            }
        ],
        capture_checkpoints=[],
    )

    assert result.ok is True
    assert result.error_code is None
    assert result.evidence["terminal_backend"] == "screen"
    assert result.evidence["required_completion"] == "review"
    assert result.evidence["steps"] == [
        {
            "key": "review",
            "expect": expected,
            "reached": True,
            "transcript": f"setup\n{expected}\n",
        }
    ]
    start = next(command for command in commands if command.startswith("screen -dmS "))
    assert shlex.split(start) == [
        "screen",
        "-dmS",
        session,
        "/bin/sh",
        "-lc",
        "/usr/local/bin/yoke onboard --project yoke",
    ]
    input_command = next(command for command in commands if " -X stuff " in command)
    assert shlex.split(input_command) == [
        "screen",
        "-S",
        session,
        "-p",
        "0",
        "-X",
        "stuff",
        sent + "\n",
    ]
    transcript_command = next(
        command for command in commands if " hardcopy -h " in command
    )
    transcript_path = f"/tmp/{session}-transcript.txt"
    assert (
        transcript_command
        == f"screen -S {session} -p 0 -X hardcopy -h {transcript_path}; "
        f"cat {transcript_path} 2>/dev/null; rm -f {transcript_path}"
    )
    assert any(command == f"screen -S {session} -X quit" for command in commands)
    assert commands[-1].find("close window id 445") >= 0
