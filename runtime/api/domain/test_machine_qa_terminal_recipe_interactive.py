"""Interactive terminal-session and typed-submission recipe coverage."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from runtime.api.domain.machine_qa_terminal_recipe_test_support import (
    SecretRecipeControl,
    completed,
    recipe,
)
from yoke_core.domain.coordination_leases import Lease
from yoke_core.domain.host_control_runner import (
    TestMachineMaterial as MachineMaterial,
)
from yoke_core.domain.machine_qa_execution import MachineQaLease
from yoke_core.domain.ssh_mac_terminal_recipe import execute_terminal_recipe
from yoke_core.domain.ssh_mac_terminal_recipe_support import (
    capture_recipe_transcript,
    send_recipe_keys,
)


def test_interactive_recipe_rejects_a_known_unexpected_exit_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[str] = []
    monkeypatch.setattr(
        "yoke_core.domain.ssh_mac_terminal_recipe.uuid4",
        lambda: SimpleNamespace(hex="c" * 32),
    )
    monkeypatch.setattr(
        "yoke_core.domain.ssh_mac_terminal_recipe.time.sleep",
        lambda _seconds: None,
    )

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
            return completed(command, stdout="ready")
        if command.startswith("cat /tmp/yoke-qa-"):
            return completed(command, stdout="7\n")
        return completed(command)

    result = execute_terminal_recipe(
        run,
        upload_bytes=lambda _path, _content: True,
        entry_surface="yoke onboard",
        required_completion="done",
        config=recipe(mode="terminal-multiplexer"),
        evidence_parent=tmp_path / "evidence",
        secret_values=(),
    )

    assert result.ok is False
    assert result.error_code == "terminal_recipe_assertion_failed"
    assert "return code 7 not in expected set" in result.evidence["assertion_failures"]
    assert commands[-3] == "screen -S yoke-qa-cccccccccccc -X quit"
    assert "close window id 445" in commands[-2]
    assert commands[-1] == "rm -f /tmp/yoke-qa-cccccccccccc.exit"


def test_screen_transcript_removes_hardcopy_nul_padding() -> None:
    def run(
        command: str,
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        return completed(command, stdout="\x00ready\x00\n")

    transcript = capture_recipe_transcript(
        run,
        backend="screen",
        session="yoke-qa-session",
    )

    assert transcript == "ready\n"
    assert "\x00" not in transcript


def test_screen_multi_key_input_settles_before_activation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[str] = []
    sleeps: list[float] = []
    monkeypatch.setattr(
        "yoke_core.domain.ssh_mac_terminal_recipe_support.time.sleep",
        lambda seconds: sleeps.append(float(seconds)),
    )

    def run(
        command: str,
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return completed(command)

    assert send_recipe_keys(
        run,
        backend="screen",
        session="yoke-qa-session",
        keys=["Down", "Down", "Enter"],
    )
    assert len(commands) == 3
    assert sleeps == [0.2, 0.2]


def test_interactive_recipe_uses_action_wait_then_global_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(
        "yoke_core.domain.ssh_mac_terminal_recipe.uuid4",
        lambda: SimpleNamespace(hex="e" * 32),
    )
    monkeypatch.setattr(
        "yoke_core.domain.ssh_mac_terminal_recipe.time.sleep",
        lambda seconds: sleeps.append(float(seconds)),
    )

    config = recipe(mode="terminal-multiplexer")
    config["actions"] = [
        {
            "step": "initial",
            "keys": [],
            "capture": False,
            "wait_seconds": 2.5,
        },
        {
            "step": "done",
            "keys": ["Enter"],
            "capture": False,
        },
    ]
    config["step_delay"] = 7.0

    def run(
        command: str,
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        if command.startswith("if command -v tmux"):
            return completed(command, stdout="screen")
        if "return id of front window" in command:
            return completed(command, stdout="445")
        if " hardcopy -h " in command:
            return completed(command, stdout="ready")
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
    assert sleeps == [0.0, 2.5, 7.0]


@pytest.mark.parametrize(
    ("backend", "expected_resize"),
    (
        (
            "tmux",
            "tmux resize-window -t yoke-qa-dddddddddddd -x 100 -y 32",
        ),
        (
            "screen",
            "screen -S yoke-qa-dddddddddddd -p 0 -X width 100 32",
        ),
    ),
)
def test_interactive_recipe_resizes_the_created_native_session(
    backend: str,
    expected_resize: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[str] = []
    monkeypatch.setattr(
        "yoke_core.domain.ssh_mac_terminal_recipe.uuid4",
        lambda: SimpleNamespace(hex="d" * 32),
    )
    monkeypatch.setattr(
        "yoke_core.domain.ssh_mac_terminal_recipe.time.sleep",
        lambda _seconds: None,
    )

    def run(
        command: str,
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        if command.startswith("if command -v tmux"):
            return completed(command, stdout=backend)
        if "return id of front window" in command:
            return completed(command, stdout="445")
        if "capture-pane" in command or " hardcopy -h " in command:
            return completed(command, stdout="ready")
        if command.startswith("cat /tmp/yoke-qa-"):
            return completed(command, stdout="0\n")
        return completed(command)

    result = execute_terminal_recipe(
        run,
        upload_bytes=lambda _path, _content: True,
        entry_surface="yoke onboard",
        required_completion="done",
        config=recipe(mode="terminal-multiplexer"),
        evidence_parent=tmp_path / "evidence",
        secret_values=(),
        terminal_size=(100, 32),
    )

    assert result.ok
    start_index = next(
        index
        for index, command in enumerate(commands)
        if command.startswith(f"{backend} ")
        and ("new-session" in command or "-dmS" in command)
    )
    resize_index = commands.index(expected_resize)
    attach_index = next(
        index for index, command in enumerate(commands) if "osascript" in command
    )
    assert start_index < resize_index < attach_index


def test_machine_lease_redacts_typed_recipe_evidence_before_submission() -> None:
    execution = MachineQaLease(
        conn=None,
        control=SecretRecipeControl(),
        material=MachineMaterial(
            project_id=1,
            project="yoke",
            settings={
                "resource_name": "test-mac",
                "host": "test-mac.local",
                "user": "tester",
                "operating_notes": "",
            },
            secrets={"ssh_private_key": "top-secret"},
        ),
        lease=Lease(
            id=1,
            project_id=1,
            lease_key="test-machine:test-mac",
            session_id="server-owned",
            acquired_at="now",
        ),
        owns_lease=False,
    )

    result = execution.execute(
        method_id="terminal-check",
        method_config=recipe(),
        entry_surface="yoke onboard",
        required_completion="done",
    )

    assert result.case_outcome == "passed"
    assert "top-secret" not in str(result.evidence)
    assert "[REDACTED]" in str(result.evidence)
