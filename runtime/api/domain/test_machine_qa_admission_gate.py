"""Admission gates the run performs as the fixture owner."""

from __future__ import annotations

import json
import subprocess

import pytest

from yoke_core.domain.machine_qa_admission_gate import run_admission_gate_with_io
from yoke_core.domain.machine_qa_recipe_contracts import (
    MachineQaRecipeError,
    validate_terminal_recipe,
)

INVITE = "yinv_fixturecode"


def _action(gate: str, **fields: object) -> dict:
    return {
        "step": "owner-step",
        "keys": [],
        "capture": False,
        "operator_gate": gate,
        "completion_text": ["Connect GitHub?"],
        "gate_timeout_seconds": 600,
        **fields,
    }


def _done(stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], returncode, stdout, "server unreachable")


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "yoke_core.domain.machine_qa_operator_gate.time.sleep", lambda _s: None
    )


def _run(gate, transcripts, replies, *, keys=None):
    reads = iter(transcripts)
    last = [""]
    calls: list[list[str]] = []

    def read() -> str:
        last[0] = next(reads, last[0])
        return last[0]

    def run_yoke(arguments):
        calls.append(list(arguments))
        return replies.pop(0)

    result = run_admission_gate_with_io(
        read_transcript=read,
        send_keys=lambda sent: (keys if keys is not None else []).append(sent) or True,
        read_exit_code=lambda _text: None,
        run_yoke=run_yoke,
        action=_action(gate),
        progress_callback=None,
    )
    return result, calls


@pytest.mark.parametrize("gate", ["admission_owner_approval", "admission_invite_entry"])
def test_contract_accepts_the_gate_without_keys(gate: str) -> None:
    recipe = {
        "actions": [_action(gate)],
        "capture_checkpoints": [],
        "execution_mode": "terminal",
        "expected_return_codes": [0],
        "expected_text": ["Connect GitHub?"],
        "max_wall_seconds": 1200,
        "notes": "admission gate",
        "post_checks": ["secret_free"],
        "setup_operations": [],
        "start_delay": 1.0,
        "step_delay": 1.0,
    }
    action = validate_terminal_recipe(recipe, required_completion="owner-step")[
        "actions"
    ][0]
    assert action["operator_gate"] == gate
    recipe["actions"] = [_action(gate, keys=["Enter"])]
    with pytest.raises(MachineQaRecipeError, match="remove keys"):
        validate_terminal_recipe(recipe, required_completion="owner-step")


def test_owner_approval_approves_the_shown_code_then_waits(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result, calls = _run(
        "admission_owner_approval",
        ["Match code: k7f2", "Match code: K7F2\nConnect GitHub?"],
        [_done()],
    )
    assert result.ok, result
    assert calls == [["machines", "approve", "K7F2"]]
    assert result.step_evidence["self_approving"] is True
    event = json.loads(capsys.readouterr().out.splitlines()[0])
    assert event["kind"] == "admission_owner_approval"


def test_owner_approval_without_a_code_refuses_with_recovery() -> None:
    result, calls = _run("admission_owner_approval", ["Choose how to join"], [])
    assert result.error_code == "admission_owner_approval_context_missing"
    assert calls == []
    assert "recovery" in result.step_evidence


def test_failed_owner_command_names_its_exit_and_recovery() -> None:
    result, _calls = _run(
        "admission_owner_approval", ["Match code: K7F2"], [_done(returncode=1)]
    )
    assert result.error_code == "admission_owner_approval_failed"
    assert result.step_evidence["exit_code"] == 1
    assert "server.log" in result.step_evidence["recovery"]


def test_invite_entry_types_the_code_and_never_records_it(
    capsys: pytest.CaptureFixture[str],
) -> None:
    typed: list = []
    reply = json.dumps({"success": True, "result": {"code": INVITE}})
    result, calls = _run(
        "admission_invite_entry",
        ["Enter invite code.", "Connect GitHub?"],
        [_done(reply)],
        keys=typed,
    )
    assert result.ok, result
    assert calls == [["invite", "Fixture Teammate", "--json"]]
    assert typed == [[INVITE, "Enter"]]
    assert INVITE not in json.dumps(result.step_evidence)
    assert INVITE not in capsys.readouterr().out


def test_invite_that_cannot_be_issued_refuses_by_name() -> None:
    result, _calls = _run(
        "admission_invite_entry", ["Enter invite code."], [_done("{}", returncode=1)]
    )
    assert result.error_code == "admission_invite_issue_failed"
    assert result.step_evidence["exit_code"] == 1


def test_invite_entry_ignores_completion_text_kept_from_an_earlier_screen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ticks = iter(range(10_000))
    monkeypatch.setattr(
        "yoke_core.domain.machine_qa_operator_gate.time.monotonic",
        lambda: float(next(ticks)),
    )
    reply = json.dumps({"success": True, "result": {"code": INVITE}})
    stale = "Earlier case\nConnect GitHub?\n"
    result, _calls = _run(
        "admission_invite_entry",
        [
            stale + "Enter invite code.",
            stale + "Enter invite code.\nConnecting your invited machine.",
            stale + "Enter invite code.\nConnecting your invited machine.",
            stale + "Enter invite code.\nConnecting your invited machine.\n"
            "Connect GitHub?",
        ],
        [_done(reply)],
        keys=[],
    )
    assert result.ok, result
    # The stale text alone never completed the step: it waited for the real screen.
    assert result.step_evidence["waited_seconds"] >= 2
