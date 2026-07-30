"""Direct Terminal.app recipe coverage."""

from __future__ import annotations

import base64
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from runtime.api.domain.machine_qa_terminal_recipe_test_support import (
    completed,
    recipe,
)
from yoke_core.domain.ssh_mac_terminal_recipe import execute_terminal_recipe


_PNG = base64.b64encode(b"\x89PNG\r\n\x1a\nuser-visible").decode("ascii")


def test_terminal_mode_launches_and_drives_terminal_app_without_a_multiplexer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[str] = []
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

    def run(
        command: str,
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        if "return id of targetWindow" in command:
            return completed(command, stdout="445")
        if "return contents of selected tab" in command:
            return completed(command, stdout="ready")
        if 'tell application "System Events"' in command:
            return completed(command, stdout="true")
        if command.startswith("cat /tmp/yoke-qa-"):
            return completed(command, stdout="0\n")
        return completed(command)

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
    assert launch.index("set bounds of targetWindow") < launch.rindex("do script")
    native_input = next(
        command for command in commands if 'tell application "System Events"' in command
    )
    assert "key code 125" in native_input
    assert "key code 36" in native_input
    assert not any("tmux " in command or "screen " in command for command in commands)


def test_terminal_app_recipe_captures_the_visible_window_region(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[str] = []
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

    def run(
        command: str,
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        if "return id of targetWindow" in command:
            return completed(command, stdout="445")
        if "set shotCmd" in command:
            return completed(command, stdout="446")
        if "return contents of selected tab" in command:
            return completed(command, stdout="ready")
        if command.startswith("/bin/test -s "):
            return completed(command, stdout=_PNG)
        if command.startswith("cat /tmp/yoke-qa-"):
            return completed(command, stdout="0\n")
        return completed(command)

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
    screenshot = next(command for command in commands if "set shotCmd" in command)
    assert "/usr/sbin/screencapture -x -R" in screenshot
    assert " -l " not in screenshot
    assert "set b to bounds of targetWindow" in screenshot
    assert any("close window id 446" in command for command in commands)
    assert any("close window id 445" in command for command in commands)
