"""Fail-closed workflow reconciliation and retrigger idempotency coverage."""

from __future__ import annotations

import subprocess
from types import SimpleNamespace
from unittest import mock

import pytest

from yoke_core.domain import deploy_pipeline_github_workflow as workflow


def _result(
    returncode: int,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr,
    )


def test_find_run_transport_failure_is_not_treated_as_not_found() -> None:
    with mock.patch.object(
        workflow,
        "_github_actions",
        return_value=_result(4, stderr="relay unavailable"),
    ), pytest.raises(workflow._WorkflowReconciliationError) as raised:
        workflow._find_existing_workflow_run(
            "upyoke/platform",
            "deploy.yml",
            "abc123",
            project="platform",
            sd=None,
        )

    assert "find-run" in str(raised.value)
    assert "relay unavailable" in str(raised.value)


def test_jobs_count_transport_failure_is_not_treated_as_zero() -> None:
    with mock.patch.object(
        workflow,
        "_github_actions",
        side_effect=[
            _result(0, stdout="77\n"),
            _result(4, stderr="hosted handler unavailable"),
        ],
    ), pytest.raises(workflow._WorkflowReconciliationError) as raised:
        workflow._find_existing_workflow_run(
            "upyoke/platform",
            "deploy.yml",
            "abc123",
            project="platform",
            sd=None,
        )

    assert "jobs-count" in str(raised.value)
    assert "hosted handler unavailable" in str(raised.value)


def test_empty_and_failed_predecessors_get_deterministic_retrigger_scopes() -> None:
    with mock.patch.object(
        workflow,
        "_github_actions",
        side_effect=[_result(0, "77\n"), _result(0, "0\n")],
    ):
        empty = workflow._find_existing_workflow_run(
            "upyoke/platform",
            "deploy.yml",
            "abc123",
            project="platform",
            sd=None,
        )

    with mock.patch.object(
        workflow,
        "_github_actions",
        side_effect=[
            _result(0, "88\n"),
            _result(0, "2\n"),
            _result(1, "failed:failure\n"),
        ],
    ):
        failed = workflow._find_existing_workflow_run(
            "upyoke/platform",
            "deploy.yml",
            "abc123",
            project="platform",
            sd=None,
        )

    assert empty == ("", False, "empty:77")
    assert failed == ("", False, "failed:88")


def test_stale_failed_run_scope_reaches_workflow_dispatch_request_id() -> None:
    github_calls: list[tuple[str, ...]] = []

    def _github_actions(*args: str, **_kwargs: object) -> subprocess.CompletedProcess:
        github_calls.append(args)
        return _result(0, "99\n")

    with mock.patch.object(
        workflow, "_check_ci_gate", return_value=(True, ""),
    ), mock.patch.object(
        workflow, "_run_cmd", return_value=_result(0, "abc123\n"),
    ), mock.patch.object(
        workflow,
        "_find_existing_workflow_run",
        return_value=("", False, "failed:88"),
    ), mock.patch.object(
        workflow, "_github_actions", side_effect=_github_actions,
    ), mock.patch.object(
        workflow, "_poll_github_actions", return_value=(0, "success"),
    ):
        result = workflow._dispatch_github_actions_workflow(
            {"workflow": "deploy.yml", "dispatch_correlation_input": "yoke_dispatch_id"},
            name="prod-deploy",
            run_id="run-1",
            member_items=[],
            github_repo="upyoke/platform",
            project="platform",
            project_repo_path="",
            timeout_min=30,
            fresh=False,
            gate_branch="main",
            release_lineage="a" * 40,
            sd="/tmp/sd",
        )

    assert result == (0, "")
    trigger = github_calls[0]
    assert trigger[trigger.index("--request-id") + 1] == (
        "deploy:platform:run-1:prod-deploy:failed:88"
    )
    assert trigger[-2:] == ("--correlation-input", "yoke_dispatch_id")


def test_each_explicit_fresh_invocation_gets_a_new_request_scope() -> None:
    github_calls: list[tuple[str, ...]] = []

    def _github_actions(*args: str, **_kwargs: object) -> subprocess.CompletedProcess:
        github_calls.append(args)
        return _result(0, "99\n")

    with mock.patch.object(
        workflow, "_check_ci_gate", return_value=(True, ""),
    ), mock.patch.object(
        workflow, "_run_cmd", return_value=_result(0, "abc123\n"),
    ), mock.patch.object(
        workflow, "_github_actions", side_effect=_github_actions,
    ), mock.patch.object(
        workflow, "_poll_github_actions", return_value=(0, "success"),
    ), mock.patch.object(
        workflow.uuid,
        "uuid4",
        side_effect=[SimpleNamespace(hex="first"), SimpleNamespace(hex="second")],
    ):
        for _ in range(2):
            result = workflow._dispatch_github_actions_workflow(
                {"workflow": "deploy.yml", "dispatch_correlation_input": "yoke_dispatch_id"},
                name="prod-deploy",
                run_id="run-1",
                member_items=[],
                github_repo="upyoke/platform",
                project="platform",
                project_repo_path="",
                timeout_min=30,
                fresh=True,
                gate_branch="main",
                release_lineage="a" * 40,
                sd="/tmp/sd",
            )
            assert result == (0, "")

    request_ids = [
        call[call.index("--request-id") + 1]
        for call in github_calls
        if call and call[0] == "trigger"
    ]
    assert request_ids == [
        "deploy:platform:run-1:prod-deploy:fresh:first",
        "deploy:platform:run-1:prod-deploy:fresh:second",
    ]
