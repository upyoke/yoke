"""Typed Machine QA operator-gate behavior."""

from __future__ import annotations

import json
import subprocess

import pytest

from runtime.api.domain.machine_qa_terminal_recipe_test_support import completed
from yoke_core.domain.machine_qa_operator_gate import (
    run_machine_browser_approval,
    run_machine_browser_approval_with_io,
)
from yoke_harness.machine_browser_approval import BrowserApprovalResult
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
            f"  {detail_marker} Open: https://app.stage.upyoke.com/connect\n",
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
        if 'tell application "Safari"' in command:
            return completed(
                command,
                stdout=(
                    "https://app.stage.upyoke.com/connect?user_code=AB12-CD34\n"
                    if "return tabURLs" in command
                    else "approved|https://app.stage.upyoke.com/connect?user_code=AB12-CD34|"
                    "https://app.stage.upyoke.com/orgs/acme/frontier\n"
                ),
            )
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
        status_path="/tmp/approval-session.exit",
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
        "approval_automation": "self_approving_visible_safari",
        "code": "AB12-CD34",
        "event": "machine_qa.operator_gate",
        "kind": "machine_browser_approval",
        "self_approving": True,
        "url": "https://app.stage.upyoke.com/connect?user_code=AB12-CD34",
    }
    assert result.browser_evidence == {
        "approval_entry": "/connect",
        "browser": "Safari",
        "result_url": "https://app.stage.upyoke.com/orgs/acme/frontier",
        "visible_control": "Approve machine",
    }


def test_browser_gate_ignores_stale_outcomes_before_current_code(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current_gate = (
        "One-time code: EF56-GH78\nOpen: https://app.stage.upyoke.com/machine\n"
    )
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
        read_exit_code=lambda _transcript: None,
        action=_gate_action(),
        progress_callback=None,
        allowed_base_urls=("https://app.stage.upyoke.com",),
        browser="Safari",
        approve_browser=lambda _url, _code: BrowserApprovalResult(
            True,
            {"browser": "Safari"},
        ),
    )

    assert result.ok is True
    assert result.error_code is None
    assert result.transcript.endswith("Yoke token connected.\n")
    assert result.browser_evidence == {"browser": "Safari"}
    assert json.loads(capsys.readouterr().out)["code"] == "EF56-GH78"


def test_browser_gate_accepts_completion_after_browser_automation_failure() -> None:
    browser_evidence = {"browser": "Safari", "state": "browser_tab_missing"}
    transcripts = iter(
        (
            "One-time code: AB12-CD34\nOpen: https://app.stage.upyoke.com/connect\n",
            "One-time code: AB12-CD34\nYoke token connected.\n",
        )
    )

    result = run_machine_browser_approval_with_io(
        read_transcript=lambda: next(transcripts),
        send_keys=lambda _keys: True,
        read_exit_code=lambda _transcript: None,
        action=_gate_action(),
        progress_callback=None,
        allowed_base_urls=("https://app.stage.upyoke.com",),
        browser="Safari",
        approve_browser=lambda _url, _code: BrowserApprovalResult(
            False,
            browser_evidence,
            "machine_browser_tab_missing",
        ),
    )

    assert result.ok is True
    assert result.error_code is None
    assert result.browser_evidence == browser_evidence
    assert result.browser_automation_error_code == "machine_browser_tab_missing"


def test_browser_gate_rejects_a_non_entry_path_before_automation() -> None:
    called: list[bool] = []
    result = run_machine_browser_approval_with_io(
        read_transcript=lambda: (
            "One-time code: AB12-CD34\nOpen: https://app.stage.upyoke.com/anything\n"
        ),
        send_keys=lambda _keys: True,
        read_exit_code=lambda _transcript: None,
        action=_gate_action(),
        progress_callback=None,
        allowed_base_urls=("https://app.stage.upyoke.com",),
        browser="Safari",
        approve_browser=lambda _url, _code: (
            called.append(True) or BrowserApprovalResult(True, {})
        ),
    )

    assert result.error_code == "machine_browser_approval_context_invalid"
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


def test_standalone_gate_accepts_the_current_complete_verification_uri():
    uri = "https://example.invalid/connect?user_code=AB12-CD34"
    transcripts = iter(
        (f"One-time code: AB12-CD34\nOpen: {uri}\n", "Yoke token connected.")
    )
    requests = []
    result = run_machine_browser_approval_with_io(
        read_transcript=lambda: next(transcripts),
        send_keys=lambda keys: True,
        read_exit_code=lambda _transcript: None,
        action=_gate_action(),
        progress_callback=None,
        allowed_base_urls=("https://example.invalid",),
        browser="Safari",
        approve_browser=lambda url, code: (
            requests.append((url, code)) or BrowserApprovalResult(True, {})
        ),
    )
    assert result.ok
    assert requests == [(uri, "AB12-CD34")]


def test_complete_uri_on_an_undeclared_origin_is_refused_before_approval():
    requests = []
    result = run_machine_browser_approval_with_io(
        read_transcript=lambda: (
            "One-time code: AB12-CD34\nOpen: https://other.invalid/connect?user_code=AB12-CD34\n"
        ),
        send_keys=lambda keys: True,
        read_exit_code=lambda _transcript: None,
        action=_gate_action(),
        progress_callback=None,
        allowed_base_urls=("https://example.invalid",),
        browser="Safari",
        approve_browser=lambda url, code: (
            requests.append((url, code)) or BrowserApprovalResult(True, {})
        ),
    )
    assert result.error_code == "machine_browser_approval_context_invalid"
    assert result.browser_evidence["recovery"]
    assert not requests


def _exiting_gate(transcripts: list[str], exit_code: int | None):
    readings = iter(transcripts)
    approvals: list[str] = []
    result = run_machine_browser_approval_with_io(
        read_transcript=lambda: next(readings),
        send_keys=lambda _keys: True,
        read_exit_code=lambda transcript: exit_code if "exit" in transcript else None,
        action=_gate_action(),
        progress_callback=None,
        allowed_base_urls=("https://app.upyoke.com",),
        browser="Chromium",
        approve_browser=lambda url, code: (
            approvals.append(code) or BrowserApprovalResult(True, {})
        ),
    )
    return result, approvals


def test_setup_exit_before_the_approval_prompt_reports_that_exit() -> None:
    refusal = "setup_terminal_ownership_lost: setup stopped. Run `yoke setup` again."
    result, approvals = _exiting_gate([f"Starting Yoke setup\n{refusal}\nexit"], 1)

    assert not result.ok
    assert result.error_code == "terminal_setup_exited"
    assert result.step_evidence["step"] == "operator-browser-approval"
    assert result.step_evidence["setup_exit"] == {"exit_code": 1, "refusal": refusal}
    assert approvals == []


def test_setup_exit_during_approval_is_named_instead_of_waiting() -> None:
    prompt = "One-time code: AB12-CD34\nOpen: https://app.upyoke.com/connect\n"
    result, approvals = _exiting_gate([prompt, prompt + "exit"], 2)

    assert result.error_code == "terminal_setup_exited"
    assert result.step_evidence["setup_exit"]["exit_code"] == 2
    assert approvals == ["AB12-CD34"]
