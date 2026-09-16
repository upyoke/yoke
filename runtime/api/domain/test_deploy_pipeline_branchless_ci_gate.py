"""CI gate coverage for a candidate frozen without a branch of its own.

An ephemeral preview deploys a commit that no long-lived branch points at.
The gate must still prove that commit's CI, and must refuse rather than
start a run it cannot aim at the frozen revision.
"""

from __future__ import annotations

import subprocess
from typing import Any, Dict, List
from unittest import mock
from urllib.parse import parse_qs, urlsplit

from runtime.api.domain.deploy_pipeline_gate_test_support import (
    ci_response as _ci_response,
    commit_file as _commit,
)
from runtime.api.domain.test_github_actions_rest import _FakeResponse, _RESOLVED
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import deploy_pipeline_gates
from yoke_core.domain import deploy_pipeline_github_workflow
from yoke_core.domain.handlers.github_actions_check_ci import handle_check_ci

# GitHub's own filter fields, keyed by the query parameter naming them.
_RUN_FIELD_BY_QUERY_KEY = {"branch": "head_branch", "head_sha": "head_sha"}


def _serve_workflow_runs(monkeypatch, universe: List[Dict[str, Any]]) -> List[str]:
    """Answer workflow-run queries the way GitHub does — by filtering.

    The defect this guards is not a malformed query string but an answer:
    a run the caller did not ask about must never come back, so the fake
    applies each supplied filter instead of returning a canned payload.
    """
    seen: List[str] = []

    def _fake_urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        seen.append(url)
        # keep_blank_values matters: GitHub honours ``branch=`` as a
        # branch named "", and dropping it here would hide the very
        # defect these tests exist to catch.
        query = parse_qs(urlsplit(url).query, keep_blank_values=True)
        matched = [
            run
            for run in universe
            if all(
                str(run.get(field, "")) == values[0]
                for key, values in query.items()
                if (field := _RUN_FIELD_BY_QUERY_KEY.get(key))
            )
        ]
        return _FakeResponse({"workflow_runs": matched})

    from yoke_core.domain import gh_rest_transport

    monkeypatch.setattr(gh_rest_transport, "urlopen", _fake_urlopen)
    return seen


def _branchless_check(head_sha: str) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="github_actions.check_ci",
        actor=ActorContext(session_id="branchless-gate-test"),
        target=TargetRef(kind="global"),
        payload={
            "repo": _RESOLVED.repo,
            "workflow": "ci.yml",
            "branch": "",
            "head_sha": head_sha,
            "project": "yoke",
        },
    )


def _completed_run(run_id: int, head_sha: str, branch: str) -> Dict[str, Any]:
    return {
        "id": run_id,
        "run_number": run_id,
        "status": "completed",
        "conclusion": "success",
        "head_sha": head_sha,
        "head_branch": branch,
    }


def test_green_run_for_another_commit_cannot_satisfy_a_branchless_lookup(
    monkeypatch,
) -> None:
    frozen_sha = "a" * 40
    other_sha = "b" * 40
    universe = [_completed_run(11, other_sha, "main")]
    monkeypatch.setattr(
        "yoke_core.domain.project_github_auth.resolve_project_github_auth",
        lambda project, **kwargs: _RESOLVED,
    )
    _serve_workflow_runs(monkeypatch, universe)

    outcome = handle_check_ci(_branchless_check(frozen_sha))

    # Dropping the branch filter must not widen the answer: a passing run
    # for a different commit is still no evidence for the frozen one.
    assert outcome.primary_success
    assert outcome.result_payload["state"] == "no_runs"

    universe.append(_completed_run(12, frozen_sha, "some-deleted-lane"))
    outcome = handle_check_ci(_branchless_check(frozen_sha))

    # The frozen commit's own run satisfies it whatever ref carried it —
    # the case an empty branch filter used to hide.
    assert outcome.result_payload["state"] == "passed"
    assert outcome.result_payload["run_id"] == 12




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
    # The recovery has to terminate: a ref alone starts no run, so the
    # steps name the dispatch and the head-commit confirmation too, and
    # never offer running the workflow against a bare commit.
    assert "Recovery, in order" in message
    assert "Dispatch platform-ci.yml explicitly on that ref" in message
    assert "resulting run's head commit is" in message
    assert "Re-run the deployment" in message
