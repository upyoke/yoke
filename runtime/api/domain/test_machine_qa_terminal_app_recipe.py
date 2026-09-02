"""Direct Terminal.app recipe coverage."""

from __future__ import annotations

import base64
from pathlib import Path
from types import SimpleNamespace

import pytest

from runtime.api.domain.machine_qa_terminal_recipe_test_support import recipe
from runtime.api.domain.scripted_mac_host_test_support import ScriptedMacHost
from yoke_core.domain.ssh_mac_terminal_recipe import execute_terminal_recipe


_PNG = base64.b64encode(b"\x89PNG\r\n\x1a\nuser-visible").decode("ascii")


class _RecipeHost(ScriptedMacHost):
    """A scripted host that also answers the recipe's transcript and status."""

    def __init__(self, *, captured_png: str | None = None) -> None:
        super().__init__()
        self.captured_png = captured_png

    def reply(self, command: str) -> str | None:
        if "return contents of selected tab" in command:
            return "ready"
        if 'tell application "System Events"' in command:
            return "true"
        if command.startswith("/bin/test -s ") and self.captured_png:
            return self.captured_png
        if command.startswith("cat /tmp/yoke-qa-"):
            return "0\n"
        return None


def test_terminal_mode_launches_and_drives_terminal_app_without_a_multiplexer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "yoke_core.domain.ssh_mac_terminal_app_recipe.uuid4",
        lambda: SimpleNamespace(hex="a" * 32),
    )
    monkeypatch.setattr(
        "yoke_core.domain.ssh_mac_terminal_app_recipe.time.sleep",
        lambda _seconds: None,
    )
    config = recipe(mode="terminal")
    config["actions"] = [
        {
            "step": "done",
            "keys": ["Down", "Enter"],
            "capture": False,
        }
    ]

    run = _RecipeHost()
    commands = run.commands

    result = execute_terminal_recipe(
        run,
        upload_bytes=lambda _path, _content: True,
        entry_surface="yoke onboard",
        required_completion="done",
        config=config,
        evidence_parent=tmp_path / "evidence",
        secret_values=(),
    )

    assert result.ok
    assert result.evidence["execution_mode"] == "terminal"
    assert result.evidence["terminal_surface"] == "Terminal.app"
    launch = next(command for command in commands if "set targetTab" in command)
    assert "do script" in launch
    placement = next(
        command for command in commands if "set bounds of targetWindow" in command
    )
    assert "set miniaturized of targetWindow to false" in placement
    native_input = next(
        command for command in commands if 'tell application "System Events"' in command
    )
    transcript_reads = [
        command for command in commands if "return contents of selected tab" in command
    ]
    assert "key code 125" in native_input
    assert "key code 36" in native_input
    assert "activate" in native_input
    assert transcript_reads
    assert all("activate" not in command for command in transcript_reads)
    assert all(
        "set index of targetWindow" not in command for command in transcript_reads
    )
    assert not any("tmux " in command or "screen " in command for command in commands)


def test_terminal_app_recipe_captures_the_visible_window_region(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "yoke_core.domain.ssh_mac_terminal_app_recipe.uuid4",
        lambda: SimpleNamespace(hex="b" * 32),
    )
    monkeypatch.setattr(
        "yoke_core.domain.ssh_mac_terminal_app_recipe.time.sleep",
        lambda _seconds: None,
    )
    config = recipe(mode="terminal")
    config["actions"] = [
        {
            "step": "done",
            "keys": [],
            "capture": True,
        }
    ]
    config["capture_checkpoints"] = ["done"]
    run = _RecipeHost(captured_png=_PNG)
    commands = run.commands
    window_ids = run.window_ids

    result = execute_terminal_recipe(
        run,
        upload_bytes=lambda _path, _content: True,
        entry_surface="yoke onboard",
        required_completion="done",
        config=config,
        evidence_parent=tmp_path / "evidence",
        secret_values=(),
    )

    assert result.ok
    handle = result.evidence["steps"][0]["artifact_handle"]
    assert handle["content_type"] == "image/png"
    screenshot = next(command for command in commands if "--cropOffset" in command)
    assert "/usr/sbin/screencapture -x -D 1" in screenshot
    assert " -R " not in screenshot
    assert " -l " not in screenshot
    # The capture window is opened by the GUI-session runner, so both the
    # driven window and its capture helper are closed afterwards.
    assert len(window_ids) >= 2
    for window_id in window_ids:
        assert any(f"close window id {window_id}" in command for command in commands)
