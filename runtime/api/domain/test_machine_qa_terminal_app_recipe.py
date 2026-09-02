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
from runtime.api.domain.terminal_display_probe_test_support import (
    DISPLAY_FRAME_PROBE_PREFIX,
    display_frame_stdout,
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
        if command.startswith(DISPLAY_FRAME_PROBE_PREFIX):
            return completed(command, stdout=display_frame_stdout())
        if "set bounds of targetWindow to {" in command:
            requested = command.split("to {")[1].split("}")[0]
            return completed(command, stdout=requested.replace(" ", ""))
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
    window_ids: list[int] = []

    def run(
        command: str,
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        if command.startswith(DISPLAY_FRAME_PROBE_PREFIX):
            return completed(command, stdout=display_frame_stdout())
        if "set bounds of targetWindow to {" in command:
            requested = command.split("to {")[1].split("}")[0]
            return completed(command, stdout=requested.replace(" ", ""))
        if "return id of targetWindow" in command:
            window_ids.append(445 + len(window_ids))
            return completed(command, stdout=str(window_ids[-1]))
        if "return contents of selected tab" in command:
            return completed(command, stdout="ready")
        if command.startswith("if /bin/test -f "):
            return completed(command, stdout="0\n")
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
    screenshot = next(
        command for command in commands if "/usr/sbin/screencapture -x -R" in command
    )
    assert " -l " not in screenshot
    # The capture window is opened by the GUI-session runner, so both the
    # driven window and its capture helper are closed afterwards.
    assert window_ids == [445, 446]
    for window_id in window_ids:
        assert any(f"close window id {window_id}" in command for command in commands)
