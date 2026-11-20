"""Native Windows desktop input: request refusals and host result mapping."""

from __future__ import annotations

import base64
import json
import subprocess

import pytest

from yoke_contracts.desktop_input import DesktopInputRefused, validate_request
from yoke_harness.native_windows import desktop_input


def _refusal(raw):
    with pytest.raises(DesktopInputRefused) as caught:
        validate_request(raw)
    return caught.value.code


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        ({"action": "scroll"}, "desktop_input_action_invalid"),
        ({"action": "focus"}, "desktop_input_window_required"),
        ({"action": "read", "title": "Codex"}, "desktop_input_element_required"),
        ({"action": "click", "title": "Codex"}, "desktop_input_click_target_invalid"),
        ({"action": "click", "title": "Codex", "x": 3}, "desktop_input_point_incomplete"),
        ({"action": "click", "title": "C", "x": 1, "y": 2, "name": "Send"}, "desktop_input_click_target_invalid"),
        ({"action": "click", "title": "C", "x": -1, "y": 2}, "desktop_input_point_invalid"),
        ({"action": "type", "title": "Codex"}, "desktop_input_text_missing"),
        ({"action": "type", "title": "Codex", "text": "a\nb"}, "desktop_input_text_invalid"),
        ({"action": "type", "title": "C", "text": "x" * 4097}, "desktop_input_text_too_long"),
        ({"action": "type", "title": "C", "text": "hi", "x": 3, "y": 4}, "desktop_input_option_unused"),
        ({"action": "keys", "title": "Codex", "keys": "ctrl+"}, "desktop_input_keys_invalid"),
        ({"action": "focus", "handle": "zz"}, "desktop_input_handle_invalid"),
        ({"action": "focus", "title": "C", "keys": "enter"}, "desktop_input_option_unused"),
        ({"action": "read", "title": "C", "index": 2}, "desktop_input_index_invalid"),
        ({"action": "windows", "wait_seconds": 61}, "desktop_input_wait_invalid"),
    ],
)
def test_invalid_requests_refuse_with_named_codes(raw, code):
    assert _refusal(raw) == code


def test_valid_request_normalizes_selectors_and_defaults():
    request = validate_request(
        {"action": "click", "process": "ChatGPT", "name": "New chat", "index": 1,
         "button": None, "double": False, "wait_seconds": 5}
    )
    assert request == {
        "action": "click", "wait_seconds": 5, "window": {"process": "ChatGPT"},
        "element": {"name": "New chat", "index": "1"}, "button": "left", "double": False,
    }
    assert validate_request({"action": "keys", "title": "C", "keys": "ctrl+a backspace"})[
        "keys"
    ] == ["ctrl+a", "backspace"]


def _host(monkeypatch, row=None, *, code=0, stdout=None, stderr=""):
    scripts = []

    def fake(control, script, *, timeout, hidden):
        scripts.append(script)
        out = stdout
        if out is None:
            out = base64.b64encode(json.dumps(row).encode()).decode() + "\n"
        return subprocess.CompletedProcess([], code, out, stderr)

    monkeypatch.setattr(desktop_input, "desktop_script", fake)
    return scripts


def test_typed_text_is_reported_only_as_its_length(monkeypatch):
    scripts = _host(monkeypatch, {"ok": True, "result": {"typed_characters": 5}})
    result = desktop_input.drive_desktop(
        object(), {"action": "type", "title": "Claude", "text": "hello"}
    )
    assert result.ok and result.evidence == {"action": "type", "typed_characters": 5}
    assert "hello" not in json.dumps(result.evidence)
    assert "hello" not in scripts[0]


@pytest.mark.parametrize(
    "text", ["ghp_" + "a" * 36, "use sk-ant-" + "b" * 20, "lease-secret-value"]
)
def test_secret_text_is_refused_before_the_host_runs(monkeypatch, text):
    scripts = _host(monkeypatch, {"ok": True, "result": {}})
    with pytest.raises(DesktopInputRefused) as caught:
        desktop_input.drive_desktop(
            object(), {"action": "type", "title": "C", "text": text},
            secrets=("lease-secret-value",),
        )
    assert caught.value.code == "desktop_input_secret_refused"
    assert scripts == []


@pytest.mark.parametrize(
    ("message", "code", "recovery"),
    [
        (
            "windows_desktop_locked: the lock screen is showing; unlock the "
            "auto-logged-on test user's console (reboot the lab so autologon "
            "signs in, or a person unlocks it over the private RDP route), then retry",
            "windows_desktop_locked",
            "unlock the auto-logged-on test user's console",
        ),
        (
            "windows_window_not_found: no visible window matches title='Codex' "
            "process='' handle=''; list windows with the `windows` action, launch "
            "the app with host-command --gui-session, or raise --wait-seconds",
            "windows_window_not_found",
            "list windows with the `windows` action",
        ),
        (
            "windows_foreground_refused: Windows kept 'X' in the foreground "
            "instead of 'Codex'; close the blocking dialog or window shown in a "
            "screenshot, then retry",
            "windows_foreground_refused",
            "close the blocking dialog",
        ),
    ],
)
def test_host_refusals_map_to_named_codes_with_recovery(monkeypatch, message, code, recovery):
    _host(monkeypatch, {"ok": False, "message": message})
    result = desktop_input.drive_desktop(object(), {"action": "focus", "title": "Codex"})
    assert not result.ok
    assert result.error_code == code
    assert result.evidence["recovery"].startswith(recovery)
    assert code not in result.evidence["detail"]


def test_unexpected_host_text_is_a_named_failure_not_a_traceback(monkeypatch):
    _host(monkeypatch, {"ok": False, "message": "Exception calling Resolve: boom"})
    result = desktop_input.drive_desktop(object(), {"action": "windows"})
    assert result.error_code == "windows_desktop_input_failed"


def test_compile_failure_and_timeout_are_named(monkeypatch):
    _host(monkeypatch, code=1, stdout="", stderr="Add-Type: CS1002 ; expected")
    failed = desktop_input.drive_desktop(object(), {"action": "windows"})
    assert failed.error_code == "windows_desktop_input_failed"
    assert "CS1002" in failed.evidence["detail"]
    _host(monkeypatch, code=124, stdout="")
    timed_out = desktop_input.drive_desktop(object(), {"action": "windows"})
    assert timed_out.error_code == "windows_desktop_task_timeout"


def test_request_rides_base64_in_the_host_script(monkeypatch):
    scripts = _host(monkeypatch, {"ok": True, "result": {"windows": []}})
    result = desktop_input.drive_desktop(object(), {"action": "windows"})
    assert result.ok and result.evidence == {"action": "windows", "windows": []}
    assert "Add-Type -ReferencedAssemblies UIAutomationClient" in scripts[0]
    assert "public static class QaDesktop" in scripts[0]
