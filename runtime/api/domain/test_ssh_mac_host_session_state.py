"""macOS root-property lock detection and Terminal launch failure evidence."""

from __future__ import annotations

import subprocess

import pytest

from yoke_harness.ssh_mac_host_session_state import (
    probe_host_display_context,
    read_display_locked,
    read_screen_sharing_active,
)
from yoke_harness.ssh_mac_terminal_app import open_terminal_app_window


# IOConsoleUsers excerpts: current macOS emits the lock flag inside this
# nested property, not as a top-level key selected by ioreg's -k option.
LOCKED_CONSOLE = """
+-o Root  <class IORegistryEntry, registered, matched, active, busy 0>
  {
    "IOConsoleUsers" = ({"kCGSSessionOnConsoleKey"=Yes,
      "CGSSessionScreenIsLocked"=Yes,"kCGSSessionUserNameKey"="yoke-test"})
  }
"""
UNLOCKED_CONSOLE = """
+-o Root  <class IORegistryEntry, registered, matched, active, busy 0>
  {
    "IOConsoleUsers" = ({"kCGSSessionOnConsoleKey"=Yes,
      "kCGSSessionUserNameKey"="yoke-test"})
  }
"""


@pytest.mark.parametrize(
    ("stdout", "expected"),
    [
        (LOCKED_CONSOLE, True),
        (LOCKED_CONSOLE.replace('"=Yes', '" = Yes'), True),
        (LOCKED_CONSOLE.replace('"=Yes', '"\t=\tYes'), True),
        (
            LOCKED_CONSOLE.replace(
                '"CGSSessionScreenIsLocked"=Yes', '"CGSSessionScreenIsLocked"=No'
            ),
            False,
        ),
        (UNLOCKED_CONSOLE, False),
    ],
)
def test_lock_flag_is_read_from_nested_console_users(stdout, expected):
    def run(command, **kwargs):
        assert command == "/usr/sbin/ioreg -n Root -d1"
        assert kwargs["timeout"] == 10
        return subprocess.CompletedProcess(command, 0, stdout, "")

    assert read_display_locked(run) is expected


def test_failed_lock_probe_is_unknown():
    def run(command, **_kwargs):
        return subprocess.CompletedProcess(command, 1, "", "ioreg failed")

    assert read_display_locked(run) is None


@pytest.mark.parametrize(
    "returncode,stdout,expected",
    [(0, "234\n", True), (0, "", False), (1, "", False), (2, "", None)],
)
def test_screen_sharing_process_probe(returncode, stdout, expected):
    def run(command, **kwargs):
        assert command == "/usr/bin/pgrep -x '(screensharingd|ScreensharingAgent)'"
        assert kwargs["timeout"] == 10
        return subprocess.CompletedProcess(command, returncode, stdout, "")

    assert read_screen_sharing_active(run) is expected


@pytest.mark.parametrize("locked", [True, False, None])
def test_only_a_confirmed_lock_checks_for_screen_sharing(monkeypatch, locked):
    from yoke_harness import ssh_mac_host_session_state as state

    commands = []
    monkeypatch.setattr(state, "read_console_user", lambda run: "test")
    monkeypatch.setattr(state, "read_display_locked", lambda run: locked)

    def run(command, **kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, "234\n", "")

    context = probe_host_display_context(run)
    assert context["display_locked"] is locked
    assert bool(commands) is (locked is True)
    assert context.get("screen_sharing_active") is (True if locked is True else None)


@pytest.mark.parametrize(
    ("returncode", "stdout", "stderr", "window_id"),
    [
        (0, "445\n", "", 445),
        (1, "445\n", "execution error: Terminal is not running (-600)", None),
        (1, "", "execution error: Not authorized (-1743)", None),
        (0, "", "", None),
        (0, "not a window", "", None),
        (0, "0", "", None),
    ],
)
def test_window_launch_keeps_osascript_evidence(returncode, stdout, stderr, window_id):
    def run(command, **_kwargs):
        return subprocess.CompletedProcess(command, returncode, stdout, stderr)

    result = open_terminal_app_window(run, command="true")

    assert result.window_id == window_id
    assert result.returncode == returncode
    assert result.stdout == stdout
    assert result.stderr == stderr
    assert result.diagnostics == {
        "osascript_exit_code": returncode,
        "osascript_stdout": stdout,
        "osascript_stderr": stderr,
    }
