"""Desktop geometry is measured in the fixture, before it is used for input."""

import base64
import re
import subprocess

import pytest

from yoke_harness import linux_display_geometry as linux
from yoke_harness import mac_desktop_geometry as mac
from yoke_harness.native_windows import console, display_geometry as windows


@pytest.mark.parametrize("has_mode", [True, False])
def test_xfce_resizes_the_unattended_display_then_reads_it_back(monkeypatch, has_mode):
    calls = []
    replies = [
        "  Width: 1280\n  Height: 1024\n  Depth: 24\n",
        "rdp0 connected primary 1280x1024+0+0\n   1280x1024     50.00*\n"
        + ("   1920x1080     50.00\n" if has_mode else ""),
    ]
    setup_calls = []
    mode = "1920x1080"
    if not has_mode:
        mode = "YokeQa-1920x1080"
        setup_calls = [
            ("xrandr", "--newmode", mode, *linux._FULL_HD_TIMING),
            ("xrandr", "--addmode", "rdp0", mode),
        ]
        replies += ["", ""]
    replies = iter(replies + ["", "  Width: 1920\n  Height: 1080\n  Depth: 24\n"])

    def run(environment, *argv):
        assert environment == {"DISPLAY": ":10"}
        calls.append(argv)
        return next(replies)

    monkeypatch.setattr(linux, "_display_command", run)
    assert linux.desktop_geometry({"DISPLAY": ":10"}, can_resize=True) == {
        "resolution": "1920x1080", "depth": 24,
    }
    assert calls == [
        ("xwininfo", "-root"), ("xrandr", "--query"),
        *setup_calls, ("xrandr", "--output", "rdp0", "--mode", mode),
        ("xwininfo", "-root"),
    ]


@pytest.mark.parametrize(
    ("output", "code"),
    [
        ("", "linux_desktop_geometry_invalid"),
        ("Width: 0\nHeight: 1024\nDepth: 24\n", "linux_desktop_resolution_too_small"),
        ("Width: 1920\nHeight: 1080\nDepth: 8\n", "linux_desktop_geometry_invalid"),
    ],
)
def test_unusable_xfce_screen_refuses_without_resizing_connected_viewer(monkeypatch, output, code):
    def probe(environment, *argv):
        assert argv == ("xwininfo", "-root")
        return output

    monkeypatch.setattr(linux, "_display_command", probe)
    with pytest.raises(RuntimeError, match=code):
        linux.desktop_geometry({"DISPLAY": ":10"}, can_resize=False)


@pytest.mark.parametrize(("resolution", "ok"), [("1920x1080", True), ("1280x1024", False)])
def test_macos_measures_console_desktop_and_refuses_an_undersized_receipt(monkeypatch, resolution, ok):
    def task(run, *, argv, timeout):
        assert argv[:2] == ("/bin/sh", "-c")
        assert "if !largeEnough(current)" in argv[2]
        assert "CGCompleteDisplayConfiguration(configuration, .forSession)" in argv[2]
        assert "mode.width >= 1920 && mode.height >= 1080" in argv[2]
        return subprocess.CompletedProcess(argv, 0, resolution, "")

    monkeypatch.setattr(mac, "run_terminal_app_command", task)
    if ok:
        assert mac.ensure_mac_desktop(None) == resolution
    else:
        with pytest.raises(RuntimeError, match="macos_desktop_resolution_unavailable"):
            mac.ensure_mac_desktop(None)


def test_native_windows_provision_installs_a_limited_console_resize_task():
    script = windows.console_display_task_script()
    assert "TASK_TRIGGER_LOGON" in script and "TASK_CONSOLE_CONNECT" in script
    assert "$displayTask.Principal.RunLevel=0" in script
    assert windows.CONSOLE_DISPLAY_TASK in script
    encoded = re.search(r"-EncodedCommand ([A-Za-z0-9+/=]+)", script)[1]
    program = base64.b64decode(encoded).decode("utf-16le")
    assert "WTSGetActiveConsoleSessionId()" in program
    assert "ChangeDisplaySettings(ref best,1)" in program
    assert "mode.width >= 1920 && mode.height >= 1080" in program


@pytest.mark.parametrize(
    ("set_resolution", "observed", "ok"),
    [(True, "1920x1080", True), (False, "1920x1080", True), (False, "1280x1024", False)],
)
def test_native_windows_reset_sets_geometry_and_verify_checks_it(monkeypatch, set_resolution, observed, ok):
    def task(control, script, *, timeout):
        method = "Ensure" if set_resolution else "Observe"
        assert f"Write-Output ([YokeDesktopGeometry]::{method}())" in script
        return subprocess.CompletedProcess([], 0, f"{observed}\n{console.RECEIPT}\n", "")

    monkeypatch.setattr(console, "desktop_script", task)
    result = console.probe_console(object(), set_resolution=set_resolution)
    assert result.ok is ok
    if ok:
        assert result.evidence["resolution"] == observed
    else:
        assert result.error_code == "windows_console_not_ready"
