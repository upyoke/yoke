"""Refusal and guidance text names the real limit and the real recovery."""

from __future__ import annotations

import pytest

from yoke_core.domain import machine_qa_method_contracts as contracts
from yoke_core.domain import qa_plan_execution_abort_cli as abort_cli
from yoke_core.domain import schema_api_context as sac
from yoke_core.domain.qa_mission_stop_settlement import stopped_mission_guidance
from yoke_core.domain.qa_plan_execution_abort_reason import ABORT_REASON_MAX_LENGTH


def test_architecture_topic_refusal_names_its_real_home() -> None:
    with pytest.raises(ValueError) as refusal:
        sac.render_topic_packet("architecture", role="main_agent")
    message = str(refusal.value)
    assert "unknown topic: architecture is not a packet topic" in message
    assert ".yoke/docs/agents/rules/architecture-model.md" in message
    assert "yoke project-structure architecture-draft get --project P" in message


def test_stopped_mission_guidance_states_the_reason_limit() -> None:
    assert f"at most {ABORT_REASON_MAX_LENGTH} characters" in stopped_mission_guidance(
        "--item YOK-1", "e-1"
    )


def test_overlong_abort_reason_refuses_by_name_before_any_call(capsys) -> None:
    reason = "blocked_on_precondition: " + "x" * ABORT_REASON_MAX_LENGTH
    with pytest.raises(SystemExit) as stop:
        abort_cli.run(["--item", "YOK-1", "--execution-id", "e-1", "--reason", reason])
    assert stop.value.code == 2
    err = capsys.readouterr().err
    assert "abort_reason_too_long" in err
    assert f"the limit is {ABORT_REASON_MAX_LENGTH}" in err
    assert "Nothing was aborted" in err


def test_long_assertion_argv_refusal_names_the_value_limit() -> None:
    with pytest.raises(contracts.MachineQaExecutionError) as refusal:
        contracts._assertion({"argv": ["python3", "-c", "x" * 2200]})
    message = str(refusal.value)
    assert "2200 characters" in message
    assert f"at most {contracts.ASSERTION_ARGV_MAX_CHARS}" in message
    assert "Split the check into several assertions" in message

