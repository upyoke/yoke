"""Terminal-screen readiness behavior for Machine QA recipes."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from runtime.api.domain.machine_qa_terminal_recipe_test_support import (
    completed,
    recipe,
)
from yoke_core.domain.ssh_mac_terminal_readiness import wait_for_ready_text
from yoke_core.domain.ssh_mac_terminal_recipe import execute_terminal_recipe


def test_ready_text_waits_for_the_expected_terminal_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transcripts = iter(("still authorizing", "Yoke token connected."))
    capture_count = 0

    def run(
        command: str,
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal capture_count
        if " hardcopy -h " in command:
            capture_count += 1
            return completed(command, stdout=next(transcripts))
        return completed(command)

    monotonic_values = iter((0.0, 1.0))
    monkeypatch.setattr(
        "yoke_core.domain.ssh_mac_terminal_readiness.time.monotonic",
        lambda: next(monotonic_values),
    )
    monkeypatch.setattr(
        "yoke_core.domain.ssh_mac_terminal_readiness.time.sleep",
        lambda _seconds: None,
    )

    ready, transcript = wait_for_ready_text(
        run,
        backend="screen",
        session="yoke-qa-session",
        expected=("Yoke token connected.",),
        timeout_seconds=5,
    )

    assert ready is True
    assert transcript == "Yoke token connected."
    assert capture_count == 2


def test_ready_text_times_out_without_sending_input(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[str] = []
    monotonic_values = iter((0.0, 0.0, 0.0, 0.0, 5.0))
    monkeypatch.setattr(
        "yoke_core.domain.ssh_mac_terminal_recipe.uuid4",
        lambda: SimpleNamespace(hex="f" * 32),
    )
    for target in (
        "yoke_core.domain.ssh_mac_terminal_recipe.time.monotonic",
        "yoke_core.domain.ssh_mac_terminal_readiness.time.monotonic",
    ):
        monkeypatch.setattr(target, lambda: next(monotonic_values))
    for target in (
        "yoke_core.domain.ssh_mac_terminal_recipe.time.sleep",
        "yoke_core.domain.ssh_mac_terminal_readiness.time.sleep",
    ):
        monkeypatch.setattr(target, lambda _seconds: None)
    config = recipe(mode="terminal")
    config["actions"] = [
        {
            "step": "apply",
            "keys": ["Enter"],
            "capture": False,
            "ready_text": ["Review what Yoke will save."],
            "ready_timeout_seconds": 1.0,
        }
    ]

    def run(
        command: str,
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        if command.startswith("if command -v tmux"):
            return completed(command, stdout="screen")
        if "return id of front window" in command:
            return completed(command, stdout="445")
        if " hardcopy -h " in command:
            return completed(command, stdout="Connect GitHub?")
        return completed(command)

    result = execute_terminal_recipe(
        run,
        upload_bytes=lambda _path, _content: True,
        entry_surface="yoke onboard",
        required_completion="apply",
        config=config,
        evidence_parent=tmp_path / "evidence",
        secret_values=(),
    )

    assert result.ok is False
    assert result.error_code == "terminal_action_not_ready"
    assert result.evidence["waiting_for"] == ["Review what Yoke will save."]
    assert not any(" stuff " in command for command in commands)
