"""The one gate a person finishes: password entry, and its bounded wait."""

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


def _action(purpose: str = "password_entry", **fields: object) -> dict:
    return {
        "step": "github-password",
        "keys": [],
        "capture": False,
        "operator_gate": "human_action",
        "human_purpose": purpose,
        "completion_text": ["Signed in."],
        "gate_timeout_seconds": 900,
        **fields,
    }


def _recipe(action: dict) -> dict:
    return {
        "actions": [action],
        "capture_checkpoints": [],
        "execution_mode": "terminal",
        "expected_return_codes": [0],
        "expected_text": ["Signed in."],
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
        "yoke_core.domain.machine_qa_operator_gate.time.monotonic",
        lambda: float(next(ticks)),
    )
    monkeypatch.setattr(
        "yoke_core.domain.machine_qa_operator_gate.time.sleep", sleeps.append
    )
    return sleeps


def test_contract_accepts_only_password_entry() -> None:
    config = validate_terminal_recipe(
        _recipe(_action()), required_completion="github-password"
    )
    action = config["actions"][0]
    assert action["human_purpose"] == "password_entry"
    assert action["keys"] == []
    assert action["gate_timeout_seconds"] == 900.0
    assert gate_needs_desktop_browser(action) is False


@pytest.mark.parametrize(
    "purpose",
    ["machine_approval", "private_invite_entry", "company_sign_in", "open_session"],
)
def test_a_step_an_agent_can_do_refuses_as_misclassified(purpose: str) -> None:
    with pytest.raises(MachineQaRecipeError, match="human_action_misclassified"):
        validate_terminal_recipe(_recipe(_action(purpose)), required_completion=None)


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ({"keys": ["A", "B"]}, "never sends input"),
        ({"ready_text": ["Password"]}, "preceding step"),
        ({"gate_timeout_seconds": 1801}, "1..1800"),
        ({"wait_seconds": 5}, "typed gate, not wait_seconds"),
        ({"password": "SECRET"}, "unknown fields"),
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
        "human_purpose": "password_entry",
        "completion_text": ["Machine connected."],
        "gate_timeout_seconds": 60,
    }
    with pytest.raises(MachineQaRecipeError, match="only to the human_action"):
        validate_terminal_recipe(_recipe(browser), required_completion=None)
    plain = {"step": "plain", "human_purpose": "password_entry"}
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


def test_password_entry_announces_the_one_step_and_waits(
    clock: list[float], capsys: pytest.CaptureFixture[str]
) -> None:
    beats: list[bool] = []
    result = _run(
        ["Password:", "Password:", "Signed in."],
        progress=lambda: beats.append(True),
    )
    assert result.ok, result
    assert result.browser_evidence is None
    assert result.step_evidence["self_approving"] is False
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    announcement = lines[0]
    assert announcement["event"] == "machine_qa.operator_gate"
    assert announcement["kind"] == "human_action"
    assert announcement["human_purpose"] == "password_entry"
    assert "Step github-password" in announcement["instructions"]
    assert LOCATION in announcement["instructions"]
    assert "never receives" in announcement["instructions"]
    assert lines[1]["event"] == "machine_qa.heartbeat"
    assert lines[1]["operator_gate"] == "human_action"
    assert beats == [True]
    assert clock == [1.0, 1.0]


def test_wait_is_bounded_and_names_the_step(clock: list[float]) -> None:
    result = _run(["Password:"], action=_action(gate_timeout_seconds=3))
    assert not result.ok
    assert result.error_code == "human_action_timed_out"
    assert "github-password" in result.step_evidence["recovery"]
    assert result.step_evidence["waited_seconds"] >= 3


def test_denial_and_exit_end_the_wait_by_name(clock: list[float]) -> None:
    denied = _run(["Password:", "Password:\nAuthorization expired"])
    assert denied.error_code == "human_action_rejected"
    exited = _run(["Password:", "Password:\nsetup_refused: no"], exit_code=1)
    assert exited.error_code == "terminal_setup_exited"
    assert exited.step_evidence["setup_exit"]["exit_code"] == 1


def test_lost_lease_renewal_stops_the_wait(clock: list[float]) -> None:
    def renew() -> None:
        raise RuntimeError("lease lost")

    result = _run(["Password:"], progress=renew)
    assert result.error_code == "human_action_heartbeat_failed"
