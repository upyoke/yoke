"""Desktop screenshot capture through the OS transport and command custody."""

import base64
import json
import shlex
import subprocess
from types import SimpleNamespace

import pytest

from runtime.api.domain.test_machine_screenshot import png
from yoke_contracts.machine_screenshot import screenshot_png
from yoke_harness.ssh_machine_screenshot import capture_desktop


@pytest.mark.parametrize("os", ["macos", "linux"])
def test_capture_uses_os_display_and_removes_remote_file(monkeypatch, os):
    commands = []
    monkeypatch.setattr(
        "yoke_harness.ssh_mac_host_session_state.probe_host_display_context",
        lambda run, **kwargs: {"console_user": "test", "display_locked": False},
    )

    def run(command, **kwargs):
        commands.append(command)
        output = (
            base64.b64encode(png()).decode() if command.startswith("base64") else ""
        )
        if "ensure_desktop(sys.stdin" in command:
            output = json.dumps(
                {"environment": {"DISPLAY": ":12"}, "desktop_session": "reused"}
            )
        tokens = shlex.split(command)
        if tokens[0] == "/usr/bin/python3" and len(tokens) == 7:
            directory = json.loads(tokens[-4])
            receipt = {
                "command_id": directory.rsplit("/", 1)[-1],
                "termination_verified": True,
                "returncode": 0,
            }
            assert json.loads(tokens[-2]) == {"DISPLAY": ":12"}
            assert json.loads(tokens[-3])[0] == "scrot"
            return subprocess.CompletedProcess(
                command, 0, "", "YOKE_COMMAND_RECEIPT:" + json.dumps(receipt) + "\n"
            )
        return subprocess.CompletedProcess(command, 0, output, "")

    monkeypatch.setattr(
        "yoke_harness.ssh_mac_gui_session.run_terminal_app_command",
        lambda run, **kwargs: run("screencapture " + " ".join(kwargs["argv"])),
    )
    result = capture_desktop(SimpleNamespace(os=os, _run=run, _user="test"))
    assert result.ok
    content, size = screenshot_png(
        result.evidence["capture_artifact"]["content_base64"]
    )
    assert content == png() and size == (80, 60)
    assert commands[-1].startswith("rm -f /tmp/yoke-desktop-")
    if os == "linux":
        assert any(
            "run_supervised(*[" in command and "scrot" in command
            for command in commands
        )
    else:
        assert any("screencapture" in command for command in commands)
