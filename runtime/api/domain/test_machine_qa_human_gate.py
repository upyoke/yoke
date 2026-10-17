"""The non-self-approving human gate: contract and bounded wait."""

from __future__ import annotations

import itertools
import json

import pytest

from yoke_core.domain.machine_qa_human_gate import run_human_action_gate_with_io
from yoke_core.domain.machine_qa_operator_gate_contract import (
    gate_needs_desktop_browser,
)
from yoke_core.domain.machine_qa_recipe_contracts import (
    MachineQaRecipeError,
    validate_terminal_recipe,
)

LOCATION = "the visible Terminal window on the test machine"


def _action(purpose: str = "machine_approval", **fields: object) -> dict:
    return {
        "step": "person-approves",
        "keys": [],
        "capture": False,
        "operator_gate": "human_action",
        "human_purpose": purpose,
        "completion_text": ["Machine connected."],
        "gate_timeout_seconds": 900,
        **fields,
    }


def _recipe(action: dict) -> dict:
    return {
        "actions": [action],
        "capture_checkpoints": [],
        "execution_mode": "terminal",
        "expected_return_codes": [0],
        "expected_text": ["Machine connected."],
        "max_wall_seconds": 1200,
        "notes": "human gate",
        "post_checks": ["secret_free"],
        "setup_operations": [],
        "start_delay": 1.0,
        "step_delay": 1.0,
    }


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Advance one second per read and record every sleep."""
    ticks = itertools.count()
    sleeps: list[float] = []
    monkeypatch.setattr(
        "yoke_core.domain.machine_qa_human_gate.time.monotonic",
        lambda: float(next(ticks)),
    )
    monkeypatch.setattr(
        "yoke_core.domain.machine_qa_human_gate.time.sleep", sleeps.append
    )
    return sleeps


@pytest.mark.parametrize(
    "purpose", ["machine_approval", "private_invite_entry", "company_sign_in"]
)
def test_contract_accepts_each_typed_purpose(purpose: str) -> None:
    config = validate_terminal_recipe(
        _recipe(_action(purpose)), required_completion="person-approves"
    )
    action = config["actions"][0]
    assert action["human_purpose"] == purpose
    assert action["keys"] == []
    assert action["gate_timeout_seconds"] == 900.0
    assert gate_needs_desktop_browser(action) is (purpose == "company_sign_in")


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ({"keys": ["A", "B"]}, "never sends input"),
        ({"ready_text": ["Invite code"]}, "preceding step"),
        ({"human_purpose": "approve_anything"}, "human_purpose must be one of"),
        ({"gate_timeout_seconds": 1801}, "1..1800"),
        ({"wait_seconds": 5}, "typed gate, not wait_seconds"),
        ({"invite_code": "SECRET"}, "unknown fields"),
    ],
)
def test_contract_refuses_input_secrets_and_unbounded_waits(
    fields: dict, message: str
) -> None:
    with pytest.raises(MachineQaRecipeError, match=message):
        validate_terminal_recipe(_recipe(_action(**fields)), required_completion=None)


def test_purpose_belongs_only_to_the_human_gate() -> None:
    browser = {
        "step": "operator-browser-approval",
        "keys": ["Enter"],
        "operator_gate": "machine_browser_approval",
        "human_purpose": "machine_approval",
        "completion_text": ["Machine connected."],
        "gate_timeout_seconds": 60,
    }
    with pytest.raises(MachineQaRecipeError, match="only to the human_action"):
        validate_terminal_recipe(_recipe(browser), required_completion=None)
    plain = {"step": "plain", "human_purpose": "machine_approval"}
    with pytest.raises(MachineQaRecipeError, match="require operator_gate"):
        validate_terminal_recipe(_recipe(plain), required_completion=None)


def _run(transcripts, *, action=None, exit_code=None, progress=None):
    reads = iter(transcripts)
    last = [""]

    def read() -> str:
        last[0] = next(reads, last[0])
        return last[0]

    return run_human_action_gate_with_io(
        read_transcript=read,
        read_exit_code=lambda _text: exit_code,
        action=action or _action(),
        progress_callback=progress,
        terminal_location=LOCATION,
    )


def test_machine_approval_announces_the_code_and_waits_for_the_person(
    clock: list[float], capsys: pytest.CaptureFixture[str]
) -> None:
    beats: list[bool] = []
    result = _run(
        [
            "Earlier run\nMachine connected.\nOne-time code: ab12-cd34\nWaiting",
            "One-time code: AB12-CD34\nWaiting",
            "One-time code: AB12-CD34\nMachine connected.",
        ],
        progress=lambda: beats.append(True),
    )
    assert result.ok, result
    assert result.browser_evidence is None
    assert result.step_evidence["self_approving"] is False
    assert result.step_evidence["code"] == "AB12-CD34"
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    announcement = lines[0]
    assert announcement["event"] == "machine_qa.operator_gate"
    assert announcement["kind"] == "human_action"
    assert announcement["self_approving"] is False
    assert (
        "yoke machine-authorization resolve AB12-CD34 --action approve"
        in announcement["instructions"]
    )
    assert lines[1]["event"] == "machine_qa.heartbeat"
    assert lines[1]["human_purpose"] == "machine_approval"
    assert beats == [True]
    assert clock == [1.0]


def test_private_invite_entry_never_receives_or_announces_the_code(
    clock: list[float], capsys: pytest.CaptureFixture[str]
) -> None:
    result = _run(
        ["Invite code: ********", "Machine connected."],
        action=_action("private_invite_entry"),
    )
    assert result.ok
    announcement = json.loads(capsys.readouterr().out.splitlines()[0])
    assert "code" not in announcement
    assert LOCATION in announcement["instructions"]
    assert "never receives the code" in announcement["instructions"]


def test_missing_code_context_refuses_with_recovery(clock: list[float]) -> None:
    result = _run(["Choose how to connect"])
    assert not result.ok
    assert result.error_code == "human_action_context_missing"
    assert "recovery" in result.step_evidence


def test_wait_is_bounded_and_names_the_purpose(clock: list[float]) -> None:
    result = _run(
        ["Invite code:"],
        action=_action("private_invite_entry", gate_timeout_seconds=3),
    )
    assert not result.ok
    assert result.error_code == "human_action_timed_out"
    assert "private_invite_entry" in result.step_evidence["recovery"]
    assert result.step_evidence["waited_seconds"] >= 3


def test_denial_and_exit_end_the_wait_by_name(clock: list[float]) -> None:
    denied = _run(
        ["One-time code: AB12-CD34", "One-time code: AB12-CD34\nAuthorization expired"]
    )
    assert denied.error_code == "human_action_rejected"
    exited = _run(
        ["Company sign-in", "Company sign-in\nsetup_refused: no"],
        action=_action("company_sign_in"),
        exit_code=1,
    )
    assert exited.error_code == "terminal_setup_exited"
    assert exited.step_evidence["setup_exit"]["exit_code"] == 1


def test_lost_lease_renewal_stops_the_wait(clock: list[float]) -> None:
    def renew() -> None:
        raise RuntimeError("lease lost")

    result = _run(["One-time code: AB12-CD34"], progress=renew)
    assert result.error_code == "human_action_heartbeat_failed"
