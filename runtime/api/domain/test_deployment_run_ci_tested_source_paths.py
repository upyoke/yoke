"""CI-tested release source: dispatch, fail-closed reads, and every bind path."""

from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

import pytest

from runtime.api.domain.handlers.deployment_handler_test_support import (
    deployment_request,
)
from yoke_core.domain import deployment_run_ci_tested_source as tested
from yoke_core.domain import deployment_run_create_write
from yoke_core.domain.gh_rest_transport import RestTransportError
from yoke_core.domain.handlers import deployment_run_creation
from yoke_core.domain.project_github_auth_models import ProjectGithubAuthError

HEAD, OLDER = "c" * 40, "a" * 40
TARGET = tested.CiGateTarget(
    project="platform",
    flow="flow",
    repo="owner/platform",
    workflow="platform-ci.yml",
    branch="main",
    token="read-token",
)
REST = "yoke_core.domain.github_actions_rest"
WRITE_AUTH = SimpleNamespace(token="write-token", repo="owner/platform")


def _no_runs(_target, path: str, _query: dict) -> object:
    if path.endswith("/commits"):
        return [{"sha": HEAD}, {"sha": OLDER}]
    return {"workflow_runs": []}


def test_dispatch_binds_exactly_the_commit_the_dispatched_run_tests():
    with (
        mock.patch.object(tested, "_auth", return_value=WRITE_AUTH),
        mock.patch(f"{REST}.rest_post", return_value={"workflow_run_id": 77}) as post,
        mock.patch.object(
            tested, "_read", return_value={"id": 77, "head_sha": HEAD}
        ) as read,
    ):
        assert tested.dispatch_branch_ci(TARGET) == HEAD

    path = post.call_args.args[0]
    assert path == "/repos/owner/platform/actions/workflows/platform-ci.yml/dispatches"
    assert post.call_args.kwargs["body"] == {"ref": "main", "return_run_details": True}
    assert post.call_args.kwargs["token"] == "write-token"
    assert post.call_args.kwargs["max_attempts"] == 1
    assert read.call_args.args[1] == "/repos/owner/platform/actions/runs/77"


def test_dispatch_failure_refuses_by_name_with_recovery():
    with (
        mock.patch.object(tested, "_auth", return_value=WRITE_AUTH),
        mock.patch(f"{REST}.rest_post", side_effect=RestTransportError("HTTP 422")),
        pytest.raises(tested.ReleaseSourceRefused) as refused,
    ):
        tested.dispatch_branch_ci(TARGET)

    assert refused.value.code == tested.UNVERIFIABLE
    assert "HTTP 422" in str(refused.value)
    assert "start platform-ci.yml on main by hand" in str(refused.value)


def test_dispatch_without_a_named_run_refuses_rather_than_guessing_a_commit():
    with (
        mock.patch.object(tested, "_auth", return_value=WRITE_AUTH),
        mock.patch(f"{REST}.rest_post", return_value=""),
        pytest.raises(tested.ReleaseSourceRefused) as refused,
    ):
        tested.dispatch_branch_ci(TARGET)

    assert refused.value.code == tested.UNVERIFIABLE
    assert "named no run and commit" in str(refused.value)


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        (RestTransportError("connection reset"), "connection reset"),
        (None, "confirm the project's ci_workflow_file"),
    ],
)
def test_unreadable_github_fails_closed(answer, expected):
    kwargs = (
        {"side_effect": answer}
        if isinstance(answer, Exception)
        else {"return_value": answer}
    )
    with (
        mock.patch(f"{REST}.rest_get", **kwargs),
        pytest.raises(tested.ReleaseSourceRefused) as refused,
    ):
        tested.newest_tested_commit(TARGET)

    assert refused.value.code == tested.UNVERIFIABLE
    assert expected in str(refused.value)


def test_missing_github_auth_fails_closed_with_repair():
    with (
        mock.patch(
            "yoke_core.domain.project_github_auth.resolve_project_github_auth",
            side_effect=ProjectGithubAuthError("platform", "no binding"),
        ),
        pytest.raises(tested.ReleaseSourceRefused) as refused,
    ):
        tested._auth("platform", "flow", {})

    assert refused.value.code == tested.UNVERIFIABLE
    assert "no binding" in str(refused.value)
    assert "Repair:" in str(refused.value)


@pytest.fixture
def gate_inputs():
    gating = [{"step_runner": "github-actions-workflow"}]
    with (
        mock.patch.object(
            tested, "_flow_facts", return_value=(gating, "persistent", "prod")
        ),
        mock.patch(
            "yoke_core.domain.project_renderer_settings.project_ci_workflow_file",
            return_value="platform-ci.yml",
        ),
        mock.patch(
            "yoke_core.domain.project_checkout_locations.checkout_for_project_slug",
            return_value="/checkout",
        ),
        mock.patch(
            "yoke_core.domain.deploy_pipeline_gates.resolve_flow_gate_branch",
            return_value="release",
        ) as branch,
        mock.patch.object(
            tested,
            "_auth",
            return_value=SimpleNamespace(token="t", repo="owner/platform"),
        ),
    ):
        yield branch


def test_gate_target_uses_the_gates_own_branch_rule(gate_inputs):
    target = tested.ci_gate_target("platform", "flow", None)

    gate_inputs.assert_called_once_with("platform", "persistent", "prod", "/checkout")
    assert (target.repo, target.workflow, target.branch, target.environment) == (
        "owner/platform",
        "platform-ci.yml",
        "release",
        "prod",
    )


def test_gate_target_is_absent_without_a_gate_branch_or_ci_stage(gate_inputs):
    gate_inputs.return_value = ""
    assert tested.ci_gate_target("platform", "flow", None) is None
    with mock.patch.object(
        tested,
        "_flow_facts",
        return_value=([{"step_runner": "warm-up"}], "persistent", ""),
    ):
        assert tested.ci_gate_target("platform", "flow", None) is None
    with mock.patch.object(tested, "_flow_facts", return_value=None):
        assert tested.ci_gate_target("platform", "missing", None) is None


def test_retry_of_an_untested_candidate_refuses_without_source_ref_advice():
    request = deployment_request(
        function="deployment_runs.create",
        payload={"project": "platform", "flow": "flow", "retry_of": "run-old"},
    )
    with (
        mock.patch.object(
            deployment_run_creation, "_retry_candidate", return_value=(HEAD, None)
        ),
        mock.patch.object(tested, "ci_gate_target", return_value=TARGET),
        mock.patch.object(tested, "_read", side_effect=_no_runs),
        mock.patch(
            "yoke_core.domain.deployment_runs_crud_mutate.create_run"
        ) as create_run,
    ):
        outcome = deployment_run_creation.handle_deployment_run_create(request)

    assert outcome.error.code == tested.UNTESTED
    assert "no --retry-of" in outcome.error.message
    assert "pass --source-ref" not in outcome.error.message
    create_run.assert_not_called()


def test_unkeyed_create_refuses_an_untested_commit_before_creating():
    with (
        mock.patch.object(tested, "ci_gate_target", return_value=TARGET),
        mock.patch.object(tested, "_read", side_effect=_no_runs),
        mock.patch.object(deployment_run_create_write, "create_run") as create_run,
        pytest.raises(tested.ReleaseSourceRefused),
    ):
        deployment_run_create_write.cmd_create_run(
            "platform", "flow", release_lineage=HEAD
        )

    create_run.assert_not_called()


def test_a_later_lineage_bind_names_the_untested_refusal():
    conn = mock.Mock()
    conn.execute.return_value.fetchone.return_value = ("flow", "platform", "prod")
    with (
        mock.patch.object(tested, "ci_gate_target", return_value=TARGET),
        mock.patch.object(tested, "_read", side_effect=_no_runs),
    ):
        refusal = tested.tested_lineage_refusal(conn, "run-1", HEAD)

    assert refusal.startswith(f"Error: {tested.UNTESTED}: release commit {HEAD}")
