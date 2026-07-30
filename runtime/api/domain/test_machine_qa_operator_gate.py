"""Typed Machine QA operator-gate behavior."""

from __future__ import annotations

import json
import subprocess

import pytest

from runtime.api.domain.machine_qa_terminal_recipe_test_support import completed
from yoke_core.domain.machine_qa_operator_gate import (
    run_machine_browser_approval,
)
from yoke_core.domain.machine_qa_recipe_contracts import (
    MachineQaRecipeError,
    validate_terminal_recipe,
)


def _gate_action() -> dict[str, object]:
    return {
        "step": "operator-browser-approval",
        "keys": ["Enter"],
        "capture": False,
        "operator_gate": "machine_browser_approval",
        "completion_text": ["Yoke token connected."],
        "gate_timeout_seconds": 60,
    }


def test_browser_gate_emits_coordinates_sends_enter_and_heartbeats(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transcripts = iter(
        (
            "Approve this machine.\n"
            "One-time code: AB12-CD34\n"
            "Open: https://app.stage.upyoke.com/machine/approve\n",
            "Waiting for browser approval",
            "Yoke token connected.",
        )
    )
    commands: list[str] = []
    heartbeats: list[bool] = []

    def run(command: str, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        if " hardcopy -h " in command:
            return completed(command, stdout=next(transcripts))
        return completed(command)

    monotonic = iter((0.0, 0.0, 1.0))
    monkeypatch.setattr(
        "yoke_core.domain.machine_qa_operator_gate.time.monotonic",
        lambda: next(monotonic),
    )
    monkeypatch.setattr(
        "yoke_core.domain.machine_qa_operator_gate.time.sleep",
        lambda _seconds: None,
    )

    result = run_machine_browser_approval(
        run,
        backend="screen",
        session="approval-session",
        action=_gate_action(),
        progress_callback=lambda: heartbeats.append(True),
        allowed_base_urls=("https://app.stage.upyoke.com",),
    )

    assert result.ok is True
    assert result.error_code is None
    assert heartbeats == [True]
    assert any(" -X stuff " in command for command in commands)
    event = json.loads(capsys.readouterr().out)
    assert event == {
        "code": "AB12-CD34",
        "event": "machine_qa.operator_gate",
        "kind": "machine_browser_approval",
        "url": "https://app.stage.upyoke.com/machine/approve",
    }


def test_operator_sleep_is_rejected_by_the_recipe_contract() -> None:
    config = {
        "actions": [
            {
                "step": "operator-browser-approval",
                "keys": [],
                "capture": False,
                "wait_seconds": 180,
            }
        ],
        "capture_checkpoints": [],
        "execution_mode": "terminal",
        "expected_return_codes": [0],
        "expected_text": ["ready"],
        "max_wall_seconds": 300,
        "notes": "No blind operator sleeps.",
        "post_checks": ["secret_free"],
        "setup_operations": [],
        "start_delay": 0,
        "step_delay": 0,
    }

    with pytest.raises(
        MachineQaRecipeError,
        match="typed gate, not wait_seconds",
    ):
        validate_terminal_recipe(
            config,
            required_completion="operator-browser-approval",
        )
