"""Standalone runners prove declared commits without publishing item lanes."""

from contextlib import nullcontext
from subprocess import CompletedProcess
from unittest.mock import Mock

import pytest

from yoke_core.domain import qa_standalone_ci as ci, qa_standalone_command as command
from yoke_core.domain.qa_case_execution_context import QaCaseExecutionError
from yoke_core.domain.qa_plan_execution_result_state import QaPlanExecutionError

SHA = "a" * 40


def _case(tmp_path, runner="ci_run"):
    return {
        "requirement_id": 42,
        "standalone_execution_id": "manual-run",
        "standalone_source_revision": SHA,
        "standalone_source_ref": "proof-tag",
        "standalone_checkout_path": str(tmp_path),
        "project": "widgets",
        "runner_id": runner,
        "method_config": {
            "command": "true",
            "ci_workflow": "proof.yml",
            "ci_workflow_inputs": {"candidate": SHA},
        },
    }


def test_command_requires_clean_exact_checkout_before_any_case_runs(
    tmp_path, monkeypatch
):
    case = _case(tmp_path, "worktree_run")
    monkeypatch.setattr(
        command,
        "_run",
        lambda argv: CompletedProcess(
            argv, 0, SHA + "\n" if "rev-parse" in argv else ""
        ),
    )
    assert command.standalone_checkout(case) == tmp_path
    monkeypatch.setattr(
        command,
        "_run",
        lambda argv: CompletedProcess(argv, 0, "b" * 40 if "rev-parse" in argv else ""),
    )
    with pytest.raises(QaPlanExecutionError, match="standalone_checkout_mismatch"):
        command.preflight_standalone_runners([case])


def test_ci_dispatch_preserves_inputs_and_records_exact_commit(tmp_path, monkeypatch):
    case = _case(tmp_path)
    monkeypatch.setattr(ci.lane, "repo_slug", lambda checkout: "acme/widgets")
    monkeypatch.setattr(
        ci.lane,
        "_git",
        lambda *args: CompletedProcess(args, 0, SHA + "\trefs/tags/proof-tag\n"),
    )
    monkeypatch.setattr(ci.lane, "github_actions_authority", nullcontext)
    dispatch = Mock(return_value="123")
    monkeypatch.setattr(ci.lane, "dispatch_workflow", dispatch)
    monkeypatch.setattr(ci.lane, "run_head_sha", lambda **kwargs: SHA)
    monkeypatch.setattr(ci.lane, "await_workflow", lambda **kwargs: (0, "success"))
    recorder = Mock(return_value=(91, 92))
    monkeypatch.setattr(ci, "_record_run", recorder)
    result = ci.execute_standalone_ci(case)
    assert result["verdict"] == "pass"
    assert result["verification_tree"]["head_sha"] == SHA
    assert result["ci_run_id"] == "123"
    assert dispatch.call_args.kwargs["branch"] == "proof-tag"
    assert dispatch.call_args.kwargs["inputs"] == {"candidate": SHA}
    assert recorder.call_args.kwargs["verdict"] == "pass"


def test_ci_ref_mismatch_refuses_before_dispatch(tmp_path, monkeypatch):
    monkeypatch.setattr(ci.lane, "repo_slug", lambda checkout: "acme/widgets")
    monkeypatch.setattr(
        ci.lane,
        "_git",
        lambda *args: CompletedProcess(args, 0, "b" * 40 + "\trefs/tags/proof-tag\n"),
    )
    dispatch = Mock()
    monkeypatch.setattr(ci.lane, "dispatch_workflow", dispatch)
    with pytest.raises(QaCaseExecutionError, match="standalone_ci_commit_mismatch"):
        ci.execute_standalone_ci(_case(tmp_path))
    dispatch.assert_not_called()


def test_ci_dispatched_run_mismatch_records_error_and_never_waits(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        ci,
        "standalone_ci_target",
        lambda *args: (tmp_path, "acme/widgets", "proof.yml", "proof-tag", SHA, {}),
    )
    monkeypatch.setattr(ci.lane, "github_actions_authority", nullcontext)
    monkeypatch.setattr(ci.lane, "dispatch_workflow", lambda **kwargs: "123")
    monkeypatch.setattr(ci.lane, "run_head_sha", lambda **kwargs: "b" * 40)
    await_run = Mock()
    monkeypatch.setattr(ci.lane, "await_workflow", await_run)
    recorder = Mock(return_value=(91, 92))
    monkeypatch.setattr(ci, "_record_run", recorder)
    result = ci.execute_standalone_ci(_case(tmp_path))
    assert result["verdict"] == "error"
    assert "standalone_ci_run_commit_mismatch" in recorder.call_args.kwargs["output"]
    await_run.assert_not_called()
