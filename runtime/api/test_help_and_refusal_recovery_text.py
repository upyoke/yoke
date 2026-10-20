"""Help and refusal text names the real limit and the real recovery."""

from __future__ import annotations

import pytest

from yoke_cli.commands import qa_case
from yoke_cli.commands.adapters import projects, qa_catalog_usage
from yoke_core.domain import machine_qa_method_contracts as contracts
from yoke_core.domain import qa_plan_execution_abort_cli as abort_cli
from yoke_core.domain import schema_api_context as sac
from yoke_core.domain.qa_mission_stop_settlement import stopped_mission_guidance
from yoke_core.domain.qa_plan_execution_abort_reason import ABORT_REASON_MAX_LENGTH
from yoke_core.domain.qa_plan_execution_cli_help import QA_PLAN_RUN_EPILOG


def test_architecture_topic_refusal_names_its_real_home() -> None:
    with pytest.raises(ValueError) as refusal:
        sac.render_topic_packet("architecture", role="main_agent")
    message = str(refusal.value)
    assert "unknown topic: architecture is not a packet topic" in message
    assert ".yoke/docs/agents/rules/architecture-model.md" in message
    assert "yoke project-structure architecture-draft get --project P" in message


def test_abort_help_states_the_reason_limit(capsys) -> None:
    assert qa_case.qa_plan_abort(["--help"]) == 0
    assert f"--reason holds at most {ABORT_REASON_MAX_LENGTH} characters" in (
        capsys.readouterr().out
    )
    assert f"--reason holds at most {ABORT_REASON_MAX_LENGTH} characters" in QA_PLAN_RUN_EPILOG
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


def test_plan_cases_sync_usage_requires_a_source_revision(capsys) -> None:
    assert "[--source-revision" not in qa_catalog_usage.PLAN_CASES_SYNC_USAGE
    assert "--source-revision FULL_SHA [--json]" in qa_catalog_usage.PLAN_CASES_SYNC_USAGE
    assert "yoke qa plan-cases replace" in qa_catalog_usage.PLAN_CASES_SYNC_USAGE


def test_patch_apply_help_names_every_op_field(capsys) -> None:
    with pytest.raises(SystemExit):
        projects.project_structure_patch_apply(["--help"])
    out = capsys.readouterr().out
    for field in ("op", "family", "attachment", "entry_key", "payload"):
        assert f"  {field} " in out
    assert '"entry_key":"tests"' in out
