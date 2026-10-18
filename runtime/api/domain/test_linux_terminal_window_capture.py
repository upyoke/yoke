"""Linux terminal checkpoints raise the session window and capture only it."""

import subprocess
from types import SimpleNamespace

import pytest

from runtime.api.domain.machine_qa_terminal_recipe_test_support import recipe
from runtime.api.domain.test_linux_desktop_capture import png
from yoke_core.domain.ssh_linux_terminal_recipe import execute_linux_recipe
from yoke_harness import ssh_linux_terminal
from yoke_harness import ssh_machine_screenshot as capture
from yoke_harness.ssh_linux_terminal import LinuxTerminal, LinuxTerminalWindowError


def _desktop(monkeypatch, *, active_name, activate_code=0):
    """Answer xdotool like an XFCE session whose active window is *active_name*."""
    commands = []

    def desktop(control, argv, **kwargs):
        commands.append(argv)
        if argv[1] == "getactivewindow":
            return subprocess.CompletedProcess(argv, 0, active_name + "\n", "")
        return subprocess.CompletedProcess(argv, activate_code, "", "")

    monkeypatch.setattr("yoke_harness.linux_desktop_session.desktop_command", desktop)
    return commands


def _terminal_with_capture():
    captures = []
    control = SimpleNamespace(
        capture_terminal_checkpoint=lambda **kw: (
            captures.append(kw) or {"artifact_handle": "window-1"}
        )
    )
    return LinuxTerminal(control), captures


def test_capture_window_activates_confirms_and_captures_the_window(monkeypatch):
    terminal, captures = _terminal_with_capture()
    commands = _desktop(monkeypatch, active_name=terminal.session)

    assert terminal.capture_window() == {"artifact_handle": "window-1"}
    assert commands == [
        ["xdotool", "search", "--name", terminal.session, "windowactivate", "--sync"],
        ["xdotool", "getactivewindow", "getwindowname"],
    ]
    assert captures == [{"focused_window": True}]


@pytest.mark.parametrize("active_name, activate_code", [("Chromium", 0), ("", 1)])
def test_capture_window_refuses_when_terminal_is_not_frontmost(
    monkeypatch, active_name, activate_code
):
    terminal, captures = _terminal_with_capture()
    _desktop(monkeypatch, active_name=active_name, activate_code=activate_code)

    with pytest.raises(LinuxTerminalWindowError) as refused:
        terminal.capture_window()
    assert refused.value.code == "linux_terminal_window_not_frontmost"
    assert refused.value.evidence["active_window"]["name"] == active_name
    assert refused.value.evidence["windowactivate"]["returncode"] == activate_code
    assert "recovery" in refused.value.evidence
    assert captures == []


def test_focused_window_capture_runs_scrot_focused(monkeypatch):
    argvs = []

    def desktop(control, argv, **kwargs):
        argvs.append(argv)
        result = subprocess.CompletedProcess(argv, 0, "", "")
        result.desktop_session = "reused"
        return result

    def run(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, png(), "")

    monkeypatch.setattr("yoke_harness.linux_desktop_session.desktop_command", desktop)
    control = SimpleNamespace(os="linux", _run=run)

    window = capture.capture_desktop(control, focused_window=True)
    desktop_capture = capture.capture_desktop(control)

    assert window.ok and window.evidence["capture_scope"] == "focused_window"
    assert desktop_capture.evidence["capture_scope"] == "desktop"
    assert argvs[0][:3] == ["scrot", "--focused", "--overwrite"]
    assert argvs[1][:2] == ["scrot", "--overwrite"]


def test_macos_focused_window_capture_refuses_with_a_named_reason():
    control = SimpleNamespace(
        os="macos", _run=lambda *a, **kw: subprocess.CompletedProcess(a, 0, "", "")
    )
    result = capture.capture_desktop(control, focused_window=True)
    assert result.error_code == "desktop_window_capture_unsupported"
    assert result.evidence["recovery"]


def _recipe_run(monkeypatch, capture_window):
    class Terminal:
        session = "fake-session"

        def __init__(self, control):
            pass

        def open(self, entry_surface, size, environment=None):
            return True

        def show(self):
            return True

        def transcript(self):
            return "ready\n__YOKE_EXIT_0\n"

        def capture_window(self):
            return capture_window()

        def close(self):
            return True

    monkeypatch.setattr(
        "yoke_core.domain.ssh_linux_terminal_recipe.LinuxTerminal", Terminal
    )
    monkeypatch.setattr(
        "yoke_core.domain.ssh_linux_terminal_recipe.send_recipe_keys",
        lambda *a, **kw: True,
    )
    config = recipe(mode="terminal-multiplexer")
    config["post_checks"] = []
    config["capture_checkpoints"] = ["done"]

    def desktop_capture():
        raise AssertionError("a terminal checkpoint must not capture the desktop")

    return execute_linux_recipe(
        SimpleNamespace(
            secret_values=(),
            _upload_bytes=lambda *a: True,
            _run=lambda *a, **kw: None,
            capture_terminal_checkpoint=desktop_capture,
        ),
        entry_surface="yoke setup",
        required_completion="done",
        config=config,
        size=(120, 40),
    )


def test_recipe_checkpoint_captures_the_terminal_window(monkeypatch):
    result = _recipe_run(monkeypatch, lambda: {"artifact_handle": "window-1"})
    assert result.ok, result.evidence
    assert result.evidence["steps"][0]["artifact_handle"] == "window-1"


def test_recipe_checkpoint_names_a_covered_terminal(monkeypatch):
    def covered():
        raise LinuxTerminalWindowError(
            "linux_terminal_window_not_frontmost", {"recovery": "close it"}
        )

    result = _recipe_run(monkeypatch, covered)
    assert result.error_code == "linux_terminal_window_not_frontmost"
    assert result.evidence["steps"][0]["key"] == "done"


def test_terminal_case_checkpoint_names_a_covered_terminal(monkeypatch):
    def covered(self):
        raise LinuxTerminalWindowError(
            "linux_terminal_window_not_frontmost", {"recovery": "close it"}
        )

    for name, method in {
        "open": lambda self, *a, **kw: True,
        "show": lambda self: True,
        "transcript": lambda self: "ready",
        "close": lambda self: True,
        "capture_window": covered,
    }.items():
        monkeypatch.setattr(LinuxTerminal, name, method)
    result = ssh_linux_terminal.run_linux_terminal_case(
        SimpleNamespace(),
        entry_surface="yoke setup",
        required_completion="ready",
        steps=[{"key": "ready", "expect": "ready"}],
        capture_checkpoints=["ready"],
    )
    assert result.error_code == "linux_terminal_window_not_frontmost"
    assert result.evidence["steps"][0]["key"] == "ready"
