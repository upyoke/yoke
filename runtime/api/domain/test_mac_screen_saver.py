"""Console-user idle preferences, verification refusal, and lock explanations."""

from __future__ import annotations

import shlex
import subprocess
from types import SimpleNamespace

import pytest

from runtime.api.domain.terminal_bridge_host_test_support import FakeMac
from yoke_harness import ssh_mac_transport
from yoke_harness.ssh_mac_host_session_state import (
    SCREEN_SAVER_DEFAULT_IDLE_SECONDS,
    SCREEN_SAVER_DISABLE_COMMAND,
    SCREEN_SAVER_ENABLED_ERROR,
    SCREEN_SAVER_PROBE_ERROR,
    read_screen_saver_idle_seconds,
)
from yoke_harness.ssh_mac_terminal_bridge_diagnose import diagnose_terminal_app_control
from yoke_harness.ssh_machine_screenshot import capture_desktop


@pytest.mark.parametrize(
    "code,stdout,stderr,expected",
    [
        (0, "0\n", "", 0),
        (0, "600\n", "", 600),
        (0, "90\n", "", 90),
        (
            1,
            "",
            "The domain/default pair of (com.apple.screensaver, idleTime) does not exist",
            SCREEN_SAVER_DEFAULT_IDLE_SECONDS,
        ),
        (1, "", "sudo: a password is required", None),
        (1, "", "defaults: permission denied", None),
        (0, "-1", "", None),
        (0, "invalid", "", None),
        (0, "", "", None),
    ],
)
def test_console_user_idle_preference(code, stdout, stderr, expected):
    def run(command, **kwargs):
        assert shlex.split(command) == [
            "/usr/bin/sudo",
            "-n",
            "-H",
            "-u",
            "console user's name",
            "/usr/bin/defaults",
            "-currentHost",
            "read",
            "com.apple.screensaver",
            "idleTime",
        ]
        assert kwargs["timeout"] == 10
        return subprocess.CompletedProcess(command, code, stdout, stderr)

    assert read_screen_saver_idle_seconds(run, "console user's name") == expected


@pytest.mark.parametrize(
    "console_user", [None, "", "root", "loginwindow", "_mbsetupuser"]
)
def test_no_graphical_login_has_no_idle_preference(console_user):
    def run(*args, **kwargs):
        pytest.fail(
            "No console user's preference may be read without a graphical login"
        )

    assert read_screen_saver_idle_seconds(run, console_user) is None


class SaverMac(FakeMac):
    def __init__(self, idle_reply, **kwargs):
        super().__init__(**kwargs)
        self.idle_reply = idle_reply

    def __call__(self, command, **kwargs):
        if "defaults -currentHost read com.apple.screensaver idleTime" in command:
            self.commands.append(command)
            code, stdout, stderr = self.idle_reply
            return subprocess.CompletedProcess(command, code, stdout, stderr)
        return super().__call__(command, **kwargs)


def control_for(mac):
    control = object.__new__(ssh_mac_transport.SshMacTransport)
    control._run = mac
    control._user = "yoke-test"
    return control


@pytest.mark.parametrize(
    "reply,minutes",
    [
        ((0, "600\n", ""), "10"),
        ((0, "90\n", ""), "1.5"),
        (
            (
                1,
                "",
                "The domain/default pair of (com.apple.screensaver, idleTime) does not exist",
            ),
            "20",
        ),
    ],
)
def test_enabled_saver_refuses_verification_before_gui_commands(reply, minutes):
    mac = SaverMac(reply)
    result = control_for(mac).check_terminal_bridge()
    assert not result.ok and result.error_code == SCREEN_SAVER_ENABLED_ERROR
    assert (
        f"screen saver will lock this Mac after {minutes} minutes"
        in result.evidence["recovery"]
    )
    assert SCREEN_SAVER_DISABLE_COMMAND in result.evidence["recovery"]
    assert all(
        "write" not in command and "osascript" not in command
        for command in mac.commands
    )


def test_disabled_saver_allows_existing_bridge_verification(monkeypatch):
    mac = SaverMac((0, "0\n", ""))
    calls = []

    def verify(run, **kwargs):
        calls.append((run, kwargs))
        return True, {"terminal_app_screenshot": True}, None

    monkeypatch.setattr(ssh_mac_transport, "verify_terminal_app_control", verify)
    result = control_for(mac).check_terminal_bridge()
    assert result.ok and result.evidence["screen_saver_idle_seconds"] == 0
    assert calls == [(mac, {"expected_console_user": "yoke-test"})]
    assert all("write" not in command for command in mac.commands)


def test_unreadable_saver_has_named_recovery():
    result = control_for(SaverMac((1, "", "permission denied"))).check_terminal_bridge()
    assert not result.ok and result.error_code == SCREEN_SAVER_PROBE_ERROR
    assert "repair read access" in result.evidence["recovery"]


@pytest.mark.parametrize("locked", [True, False])
@pytest.mark.parametrize("operation", ["screenshot", "diagnose", "verify"])
def test_console_mismatch_does_not_read_another_users_preference(operation, locked):
    mac = SaverMac((0, "0\n", ""), console_user="another-login", locked=locked)
    if operation == "screenshot":
        result = capture_desktop(
            SimpleNamespace(os="macos", _run=mac, _user="yoke-test")
        )
    elif operation == "diagnose":
        result = diagnose_terminal_app_control(mac, expected_console_user="yoke-test")
    else:
        result = control_for(mac).check_terminal_bridge()
    result = control_for(mac).check_terminal_bridge()
    assert not result.ok and result.error_code == "terminal_console_user_mismatch"
    assert not any("defaults" in command for command in mac.commands)


@pytest.mark.parametrize("operation", ["screenshot", "diagnose"])
@pytest.mark.parametrize("sharing", [True, False])
def test_locked_refusal_combines_saver_and_curtain_recovery(operation, sharing):
    class LockedMac(SaverMac):
        def __call__(self, command, **kwargs):
            if "pgrep" in command:
                return subprocess.CompletedProcess(
                    command, 0 if sharing else 1, "234\n" if sharing else "", ""
                )
            return super().__call__(command, **kwargs)

    mac = LockedMac((0, "1200\n", ""), locked=True)
    if operation == "screenshot":
        result = capture_desktop(
            SimpleNamespace(os="macos", _run=mac, _user="yoke-test")
        )
        evidence = result.evidence
        assert "capture_artifact" not in evidence
    else:
        result = diagnose_terminal_app_control(mac, expected_console_user="yoke-test")
        evidence = next(
            row for row in result.evidence["checks"] if row["name"] == "console_session"
        )
    assert not result.ok and result.error_code == "terminal_display_locked"
    assert "screen saver will lock this Mac after 20 minutes" in evidence["recovery"]
    assert SCREEN_SAVER_DISABLE_COMMAND in evidence["recovery"]
    assert ("curtained" in evidence["recovery"]) is sharing
    assert all("write" not in command for command in mac.commands)
