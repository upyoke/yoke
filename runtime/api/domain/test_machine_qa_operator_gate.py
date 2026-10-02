"""Typed Machine QA operator-gate behavior."""

from __future__ import annotations

import json
from functools import partial
import subprocess

import pytest

from runtime.api.domain.machine_qa_terminal_recipe_test_support import completed
from yoke_core.domain.machine_qa_operator_gate import (
    run_machine_browser_approval as _run_machine_browser_approval,
    run_machine_browser_approval_with_io as _run_machine_browser_approval_with_io,
)
from yoke_core.domain.machine_qa_saved_profile_approval import BrowserApprovalResult
from yoke_core.domain.machine_qa_recipe_contracts import (
    MachineQaRecipeError,
    validate_terminal_recipe,
)


from runtime.api.domain.machine_qa_browser_flow_test_support import EXAMPLE_FLOW

run_machine_browser_approval = partial(_run_machine_browser_approval, flow=EXAMPLE_FLOW)
run_machine_browser_approval_with_io = partial(
    _run_machine_browser_approval_with_io, flow=EXAMPLE_FLOW
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


@pytest.mark.parametrize("detail_marker", ("-", "•"))
def test_browser_gate_emits_coordinates_sends_enter_and_heartbeats(
    detail_marker: str,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transcripts = iter(
        (
            "Approve this machine.\n"
            f"  {detail_marker} One-time code: AB12-CD34\n"
            f"  {detail_marker} Open: https://app.example.test/connect\n",
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
        allowed_base_urls=("https://app.example.test",),
        approve_browser=lambda _url, _code: BrowserApprovalResult(
            True, {"browser": "candidate-daemon"}
        ),
    )

    assert result.ok is True
    assert result.error_code is None
    assert heartbeats == [True]
    assert any(" -X stuff " in command for command in commands)
    event = json.loads(capsys.readouterr().out)
    assert event == {
        "approval_automation": "self_approving_saved_profile",
        "code": "AB12-CD34",
        "event": "machine_qa.operator_gate",
        "kind": "machine_browser_approval",
        "self_approving": True,
        "url": "https://app.example.test/connect",
    }
    assert result.browser_evidence == {"browser": "candidate-daemon"}


def test_browser_gate_ignores_stale_outcomes_before_current_code(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current_gate = "One-time code: EF56-GH78\nOpen: https://app.example.test/machine\n"
    retained_history = "Yoke token connected.\nauthorization expired\n"
    transcripts = iter(
        (
            retained_history + current_gate,
            retained_history + current_gate + "Waiting for browser approval\n",
            retained_history + current_gate + "Yoke token connected.\n",
        )
    )
    monotonic = iter((0.0, 0.0, 1.0))
    monkeypatch.setattr(
        "yoke_core.domain.machine_qa_operator_gate.time.monotonic",
        lambda: next(monotonic),
    )
    monkeypatch.setattr(
        "yoke_core.domain.machine_qa_operator_gate.time.sleep",
        lambda _seconds: None,
    )

    result = run_machine_browser_approval_with_io(
        read_transcript=lambda: next(transcripts),
        send_keys=lambda _keys: True,
        action=_gate_action(),
        progress_callback=None,
        allowed_base_urls=("https://app.example.test",),
        approve_browser=lambda _url, _code: BrowserApprovalResult(
            True,
            {"browser": "candidate-daemon"},
        ),
    )

    assert result.ok is True
    assert result.error_code is None
    assert result.transcript.endswith("Yoke token connected.\n")
    assert result.browser_evidence == {"browser": "candidate-daemon"}
    assert json.loads(capsys.readouterr().out)["code"] == "EF56-GH78"


def test_browser_gate_refuses_completion_after_browser_automation_failure() -> None:
    browser_evidence = {"browser": "candidate-daemon", "state": "browser_tab_missing"}
    transcripts = iter(
        (
            "One-time code: AB12-CD34\nOpen: https://app.example.test/connect\n",
            "One-time code: AB12-CD34\nYoke token connected.\n",
        )
    )

    result = run_machine_browser_approval_with_io(
        read_transcript=lambda: next(transcripts),
        send_keys=lambda _keys: True,
        action=_gate_action(),
        progress_callback=None,
        allowed_base_urls=("https://app.example.test",),
        approve_browser=lambda _url, _code: BrowserApprovalResult(
            False,
            browser_evidence,
            "machine_browser_tab_missing",
        ),
    )

    assert result.ok is False
    assert result.error_code == "machine_browser_tab_missing"
    assert result.browser_evidence == browser_evidence
    assert result.browser_automation_error_code == "machine_browser_tab_missing"


def test_browser_gate_rejects_a_non_entry_path_before_automation() -> None:
    called: list[bool] = []
    result = run_machine_browser_approval_with_io(
        read_transcript=lambda: (
            "One-time code: AB12-CD34\nOpen: https://app.example.test/anything\n"
        ),
        send_keys=lambda _keys: True,
        action=_gate_action(),
        progress_callback=None,
        allowed_base_urls=("https://app.example.test",),
        approve_browser=lambda _url, _code: (
            called.append(True) or BrowserApprovalResult(True, {})
        ),
    )

    assert result.error_code == "machine_browser_approval_context_missing"
    assert called == []


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


def test_browser_gate_reads_the_latest_link_and_counts_automation_time(monkeypatch):
    clock = iter((0.0, 61.0))
    monkeypatch.setattr(
        "yoke_core.domain.machine_qa_operator_gate.time.monotonic", lambda: next(clock)
    )
    seen = []
    current = "One-time code: EF56-GH78\nOpen: https://app.example.test/machine\n"
    history = "One-time code: AB12-CD34\nOpen: https://app.example.test/connect\n"
    result = run_machine_browser_approval_with_io(
        read_transcript=lambda: history + current,
        send_keys=lambda keys: True,
        action=_gate_action(),
        progress_callback=None,
        allowed_base_urls=("https://app.example.test",),
        approve_browser=lambda url, code: (
            seen.append((url, code)) or BrowserApprovalResult(True, {})
        ),
    )
    assert seen == [("https://app.example.test/machine", "EF56-GH78")]
    assert result.error_code == "machine_browser_approval_timed_out"
