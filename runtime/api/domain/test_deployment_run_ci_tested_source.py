"""A CI-gated release binds a commit that has its own CI run."""

from __future__ import annotations

from unittest import mock

import pytest

from runtime.api.domain.handlers.deployment_handler_test_support import (
    deployment_request,
)
from yoke_core.domain import deployment_run_ci_tested_source as tested
from yoke_core.domain.handlers import deployment_run_creation

HEAD, MIDDLE, OLDEST = "c" * 40, "b" * 40, "a" * 40
TARGET = tested.CiGateTarget(
    project="platform",
    repo="owner/platform",
    workflow="platform-ci.yml",
    branch="main",
    token="token",
)


def _run(sha: str, status: str, conclusion: str | None, number: int) -> dict:
    return {
        "id": number,
        "run_number": number,
        "head_sha": sha,
        "status": status,
        "conclusion": conclusion,
    }


def _github(runs: list[dict]):
    """Answer the two reads creation makes: branch runs and branch commits."""

    def read(_target, path: str, query: dict) -> object:
        if path.endswith("/commits"):
            return [{"sha": sha} for sha in (HEAD, MIDDLE, OLDEST)]
        wanted = query.get("head_sha")
        return {
            "workflow_runs": [
                run for run in runs if not wanted or run["head_sha"] == wanted
            ]
        }

    return read


@pytest.fixture
def gated():
    with mock.patch.object(tested, "ci_gate_target", return_value=TARGET):
        yield


def test_default_binds_newest_commit_with_its_own_run_when_head_has_none(gated):
    runs = [
        _run(MIDDLE, "in_progress", None, 2),
        _run(OLDEST, "completed", "success", 1),
    ]
    with mock.patch.object(tested, "_read", side_effect=_github(runs)):
        bound = tested.bind_tested_release_source("platform", "flow", None, None)

    assert bound == MIDDLE


def test_default_skips_a_commit_whose_newest_run_failed(gated):
    runs = [
        _run(HEAD, "completed", "failure", 3),
        _run(OLDEST, "completed", "success", 1),
    ]
    with mock.patch.object(tested, "_read", side_effect=_github(runs)):
        bound = tested.bind_tested_release_source("platform", "flow", None, "")

    assert bound == OLDEST


def test_explicit_untested_commit_refuses_naming_the_newest_tested(gated):
    runs = [_run(MIDDLE, "completed", "success", 2)]
    with (
        mock.patch.object(tested, "_read", side_effect=_github(runs)),
        pytest.raises(tested.ReleaseSourceRefused) as refused,
    ):
        tested.bind_tested_release_source("platform", "flow", None, HEAD)

    assert refused.value.code == "release_source_untested"
    message = str(refused.value)
    assert f"release commit {HEAD} has no run of its own" in message
    assert f"create the run on {MIDDLE}" in message
    assert "Nothing was created" in message


def test_explicit_commit_with_its_own_run_is_kept(gated):
    runs = [_run(OLDEST, "completed", "success", 1)]
    with mock.patch.object(tested, "_read", side_effect=_github(runs)):
        bound = tested.bind_tested_release_source("platform", "flow", None, OLDEST)

    assert bound == OLDEST


def test_no_tested_commit_in_the_window_refuses_by_name(gated):
    with (
        mock.patch.object(tested, "_read", side_effect=_github([])),
        pytest.raises(tested.ReleaseSourceRefused) as refused,
    ):
        tested.bind_tested_release_source("platform", "flow", None, None)

    assert refused.value.code == "release_source_untested"
    assert "owner/platform@main" in str(refused.value)


def test_flow_without_a_ci_gate_keeps_the_given_lineage():
    with (
        mock.patch.object(tested, "ci_gate_target", return_value=None),
        mock.patch.object(tested, "_read") as read,
    ):
        assert tested.bind_tested_release_source("p", "f", None, HEAD) == HEAD
        assert tested.bind_tested_release_source("p", "f", None, None) is None

    read.assert_not_called()


@pytest.mark.parametrize(
    ("stage", "waits"),
    [
        ({"step_runner": "github-actions-workflow"}, True),
        ({"step_runner": "github-actions-workflow", "wait_for_ci": False}, False),
        ({"step_runner": "warm-up"}, False),
    ],
)
def test_only_a_github_workflow_stage_that_waits_for_ci_gates(stage, waits):
    assert tested._waits_for_ci(stage) is waits


def test_create_refusal_mints_no_run():
    request = deployment_request(
        function="deployment_runs.create",
        payload={"project": "platform", "flow": "flow", "release_lineage": HEAD},
    )
    refusal = tested.ReleaseSourceRefused("release_source_untested", "untested")
    with (
        mock.patch.object(
            deployment_run_creation, "deploy_lock_refusal", return_value=None
        ),
        mock.patch.object(tested, "bind_tested_release_source", side_effect=refusal),
        mock.patch(
            "yoke_core.domain.deployment_runs_crud_mutate.create_run"
        ) as create_run,
    ):
        outcome = deployment_run_creation.handle_deployment_run_create(request)

    assert outcome.primary_success is False
    assert outcome.error.code == "release_source_untested"
    create_run.assert_not_called()


@pytest.mark.parametrize(
    "flags",
    [["--project-repo-path", "/checkout"], ["--source-ref", HEAD]],
)
def test_cli_names_a_commit_only_with_both_checkout_and_ref(flags, capsys):
    from yoke_cli.commands.adapters import deployment_run_create

    code = deployment_run_create.deployment_runs_create(
        ["platform", "flow", "--idempotency-key", "k", *flags]
    )

    assert code == 2
    assert "Omit both to bind the newest CI-tested commit" in capsys.readouterr().err
