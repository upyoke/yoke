"""CI gate coverage for a candidate frozen without a branch of its own.

An ephemeral preview deploys a commit that no long-lived branch points at.
The gate must still prove that commit's CI, and must refuse rather than
start a run it cannot aim at the frozen revision.
"""

from __future__ import annotations

import subprocess
from unittest import mock

from runtime.api.domain.deploy_pipeline_gate_test_support import (
    ci_response as _ci_response,
    commit_file as _commit,
)
from yoke_core.domain import deploy_pipeline_gates
from yoke_core.domain import deploy_pipeline_github_workflow


def test_itemless_preview_stage_verifies_frozen_commit_without_a_branch(
    tmp_path,
) -> None:
    repo = tmp_path / "product"
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    frozen_sha = _commit(repo, "app.py", "print('preview')\n")

    ci_calls: list[tuple[str, ...]] = []

    def ci_actions(*args: str, **_kwargs):
        ci_calls.append(args)
        return _ci_response("passed")

    with (
        mock.patch.object(
            deploy_pipeline_gates,
            "project_ci_workflow_file",
            return_value="ci.yml",
        ),
        mock.patch.object(
            deploy_pipeline_gates, "_github_actions", side_effect=ci_actions,
        ),
        mock.patch.object(
            deploy_pipeline_github_workflow,
            "_find_existing_workflow_run",
            return_value=("", False, ""),
        ),
        mock.patch.object(
            deploy_pipeline_github_workflow,
            "_github_actions",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0, stdout="preview-run\n", stderr="",
            ),
        ),
        mock.patch.object(
            deploy_pipeline_github_workflow,
            "_poll_github_actions",
            return_value=(0, "completed: success"),
        ),
    ):
        result = deploy_pipeline_github_workflow._dispatch_github_actions_workflow(
            {
                "workflow": "preview-deploy.yml",
                "dispatch_correlation_input": "yoke_dispatch_id",
                "reconcile_by_head_sha": False,
            },
            name="preview-deploy",
            run_id="run-preview-test",
            member_items=[],
            github_repo="owner/product",
            project="product",
            project_repo_path=str(repo),
            timeout_min=1,
            fresh=False,
            gate_branch="",
            release_lineage=frozen_sha,
            sd=None,
        )

    assert result == (0, "")
    # The frozen candidate has no branch, so the gate proves CI from the
    # commit alone rather than filtering on a branch name nothing matches.
    assert [call[0] for call in ci_calls] == ["check-ci"]
    check = ci_calls[0]
    assert check[check.index("--branch") + 1] == ""
    assert check[check.index("--head-sha") + 1] == frozen_sha


def test_branchless_missing_run_refuses_rather_than_dispatching() -> None:
    calls: list[tuple[str, ...]] = []

    def github_actions(*args: str, **_kwargs):
        calls.append(args)
        return _ci_response("no_runs")

    with (
        mock.patch.object(
            deploy_pipeline_gates,
            "project_ci_workflow_file",
            return_value="platform-ci.yml",
        ),
        mock.patch.object(
            deploy_pipeline_gates,
            "_github_actions",
            side_effect=github_actions,
        ),
    ):
        passed, message = deploy_pipeline_gates._check_ci_gate(
            "owner/platform",
            "platform",
            30,
            branch="",
            head_sha="b" * 40,
        )

    assert passed is False
    # No ref exists to dispatch from, so the gate refuses instead of
    # triggering the workflow against an empty ref or an unrelated branch.
    assert [call[0] for call in calls] == ["check-ci"]
    assert "b" * 40 in message
    assert "no gate branch to dispatch one from" in message
    assert "Recovery:" in message
