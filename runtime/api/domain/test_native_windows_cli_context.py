"""Cursor installation requires the existing user's interactive logon token."""

import json
import subprocess

import pytest

from yoke_harness.native_windows import harness_clis


@pytest.mark.parametrize("action,harness,expected", [
    ("install", "cursor", "desktop"),
    ("install", "claude-code", "ssh"),
    ("install", "codex", "ssh"),
    ("probe", "cursor", "ssh"),
])
def test_only_cursor_install_uses_interactive_token(monkeypatch, action, harness, expected):
    calls = []
    result = {"install_exit_code": 0, "probe": {"version": "1.2.3"}}

    class Control:
        def _run(self, script, *, timeout):
            calls.append(("ssh", script, timeout))
            return subprocess.CompletedProcess([], 0, json.dumps(result), "")

    control = Control()

    def desktop(actual_control, script, *, timeout):
        assert actual_control is control
        calls.append(("desktop", script, timeout))
        return subprocess.CompletedProcess([], 0, json.dumps(result), "")

    monkeypatch.setattr(harness_clis, "desktop_script", desktop)
    payload = [harness, ["agent"], "", "1.2.3"]
    if action == "probe":
        payload = [payload]
    assert harness_clis.host_program(control, action, payload, 123, r"\d+\.\d+\.\d+") == result
    assert len(calls) == 1
    assert calls[0][0] == expected
    assert calls[0][2] == 123
    if harness == "cursor" and action == "install":
        assert "VendorScript 'https://cursor.com/install?win32=true'" in calls[0][1]
        assert "Probe $payload[1]" in calls[0][1]


@pytest.mark.parametrize("failure", ["missing_session", "cleanup", "installer"])
def test_interactive_refusal_never_falls_back_to_ssh(monkeypatch, failure):
    class Control:
        def _run(self, *_args, **_kwargs):
            pytest.fail("Cursor installation must not fall back to the SSH token")

    original = RuntimeError("windows_desktop_task_" + failure)

    def desktop(*_args, **_kwargs):
        if failure == "installer":
            return subprocess.CompletedProcess([], 9, "", "vendor refused")
        raise original

    monkeypatch.setattr(harness_clis, "desktop_script", desktop)
    with pytest.raises(RuntimeError) as error:
        harness_clis.host_program(Control(), "install", ["cursor", ["agent"], "", "1.2.3"], 30, "version")
    if failure == "installer":
        assert "windows_harness_cli_failed" in str(error.value)
        assert "vendor refused" in str(error.value)
    else:
        assert error.value is original
