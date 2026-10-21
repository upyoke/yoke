"""A CI-gated release binds a commit that has its own CI run."""

from __future__ import annotations

from unittest import mock

import pytest

from runtime.api.domain.handlers.deployment_handler_test_support import (
    deployment_request,
)
from yoke_core.domain import deployment_run_ci_tested_source as tested
from yoke_core.domain import deployment_run_gate_branch_lineage as lineage
from yoke_core.domain.handlers import deployment_run_creation

HEAD, MIDDLE, OLDEST = "c" * 40, "b" * 40, "a" * 40
TARGET = tested.CiGateTarget(
    project="platform",
    flow="flow",
    repo="owner/platform",
    workflow="platform-ci.yml",
    branch="main",
    token="token",
    environment="prod",
)


def _run(
    sha: str,
    status: str,
    conclusion: str | None,
    number: int,
    *,
    event: str = "push",
    branch: str = "main",
) -> dict:
    return {
        "id": number,
        "run_number": number,
        "head_sha": sha,
        "head_branch": branch,
        "event": event,
        "status": status,
        "conclusion": conclusion,
    }


def _commit(sha: str, *parents: str) -> dict:
    return {"sha": sha, "parents": [{"sha": parent} for parent in parents]}


TRUNK = [_commit(HEAD, MIDDLE), _commit(MIDDLE, OLDEST), _commit(OLDEST)]


def _github(runs: list[dict], commits: list[dict] = TRUNK):
    """Answer the two reads creation makes: branch runs and branch commits."""

    def read(_target, path: str, query: dict) -> object:
        if path.endswith("/commits"):
            return commits
        wanted = query.get("head_sha")
        return {
            "workflow_runs": [
                run for run in runs if not wanted or run["head_sha"] == wanted
            ]
        }

    return read


@pytest.fixture
def gated():
    with (
        mock.patch.object(tested, "ci_gate_target", return_value=TARGET),
        mock.patch.object(lineage, "previous_release", return_value=None),
    ):
        yield


@pytest.mark.parametrize(
    "status,conclusion", [("in_progress", None), ("completed", "success")]
)
def test_default_binds_tip_with_own_usable_run_without_dispatch(
    gated, status, conclusion
):
    runs = [_run(HEAD, status, conclusion, 3), _run(OLDEST, "completed", "success", 1)]
    with (
        mock.patch.object(tested, "_read", side_effect=_github(runs)),
        mock.patch.object(tested, "dispatch_branch_ci") as dispatch,
    ):
        assert tested.bind_tested_release_source("platform", "flow", None, None) == HEAD
    dispatch.assert_not_called()


@pytest.mark.parametrize("conclusion", ["failure", "cancelled"])
def test_default_refuses_tip_whose_newest_run_is_unusable(gated, conclusion):
    runs = [
        _run(HEAD, "completed", conclusion, 3),
        _run(HEAD, "completed", "success", 2),
        _run(OLDEST, "completed", "success", 1),
    ]
    with (
        mock.patch.object(tested, "_read", side_effect=_github(runs)),
        mock.patch.object(tested, "dispatch_branch_ci") as dispatch,
        pytest.raises(tested.ReleaseSourceRefused) as refused,
    ):
        tested.bind_tested_release_source("platform", "flow", None, "")
    assert refused.value.code == "release_source_ci_failed"
    assert HEAD in str(refused.value)
    assert "fix main and rerun CI" in str(refused.value)
    assert "--source-ref with a passing run" in str(refused.value)
    dispatch.assert_not_called()


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
    assert f"pass --source-ref {MIDDLE}" in message
    assert "Nothing was bound" in message


def test_explicit_commit_with_its_own_run_is_kept(gated):
    runs = [_run(OLDEST, "completed", "success", 1)]
    with mock.patch.object(tested, "_read", side_effect=_github(runs)):
        bound = tested.bind_tested_release_source("platform", "flow", None, OLDEST)

    assert bound == OLDEST


def test_default_dispatches_tip_even_when_older_commits_have_runs(gated):
    with (
        mock.patch.object(
            tested,
            "_read",
            side_effect=_github([_run(MIDDLE, "completed", "success", 1)]),
        ),
        mock.patch.object(tested, "dispatch_branch_ci", return_value=HEAD) as dispatch,
    ):
        bound = tested.bind_tested_release_source("platform", "flow", None, None)

    assert bound == HEAD
    dispatch.assert_called_once_with(TARGET)


def test_explicit_untested_commit_with_no_tested_commit_teaches_dispatch(gated):
    with (
        mock.patch.object(tested, "_read", side_effect=_github([])),
        mock.patch.object(tested, "dispatch_branch_ci") as dispatch,
        pytest.raises(tested.ReleaseSourceRefused) as refused,
    ):
        tested.bind_tested_release_source("platform", "flow", None, HEAD)

    dispatch.assert_not_called()
    assert "omit --source-ref: creation then dispatches platform-ci.yml" in str(
        refused.value
    )


def test_flow_without_a_ci_gate_keeps_the_given_lineage():
    with (
        mock.patch.object(tested, "ci_gate_target", return_value=None),
        mock.patch.object(tested, "_read") as read,
    ):
        assert tested.bind_tested_release_source("p", "f", None, HEAD) == HEAD
        assert tested.bind_tested_release_source("p", "f", None, None) is None

    read.assert_not_called()


@pytest.mark.parametrize(
    "event,branch",
    [
        ("merge_group", "main"),
        ("pull_request", "main"),
        ("pull_request_target", "main"),
        ("push", "lane"),
    ],
)
def test_default_dispatches_when_tip_has_only_foreign_runs(gated, event, branch):
    runs = [
        _run(HEAD, "completed", "success", 3, event=event, branch=branch),
        _run(MIDDLE, "completed", "success", 1),
    ]
    with (
        mock.patch.object(tested, "_read", side_effect=_github(runs)),
        mock.patch.object(tested, "dispatch_branch_ci", return_value=HEAD) as dispatch,
    ):
        assert tested.bind_tested_release_source("platform", "flow", None, None) == HEAD
    dispatch.assert_called_once_with(TARGET)


def test_default_refuses_a_commit_off_the_previous_release_lineage(gated):
    runs = [_run(HEAD, "completed", "success", 1)]
    with (
        mock.patch.object(tested, "_read", side_effect=_github(runs)),
        mock.patch.object(lineage, "previous_release", return_value=("run-9", MIDDLE)),
        mock.patch.object(lineage, "_compare_status", return_value="diverged"),
        pytest.raises(tested.ReleaseSourceRefused) as refused,
    ):
        tested.bind_tested_release_source("platform", "flow", None, None)

    assert refused.value.code == lineage.OFF_LINEAGE
    message = str(refused.value)
    assert f"selected release commit {HEAD}" in message
    assert f"does not descend from {MIDDLE}, the lineage run-9" in message
    assert "for platform in prod (GitHub compares them as diverged)" in message
    assert "--source-ref COMMIT" in message
    assert "Nothing was bound" in message


@pytest.mark.parametrize(
    ("previous", "status", "compared"),
    [
        (("run-9", MIDDLE), "ahead", True),
        (("run-9", HEAD), "unused", False),
        (("run-9", ""), "unused", False),
        (None, "unused", False),
    ],
)
def test_default_binds_a_commit_carrying_the_previous_release(
    gated, previous, status, compared
):
    runs = [_run(HEAD, "completed", "success", 1)]
    with (
        mock.patch.object(tested, "_read", side_effect=_github(runs)),
        mock.patch.object(lineage, "previous_release", return_value=previous),
        mock.patch.object(lineage, "_compare_status", return_value=status) as compare,
    ):
        bound = tested.bind_tested_release_source("platform", "flow", None, None)

    assert bound == HEAD
    assert compare.called is compared


def test_explicit_commit_skips_the_previous_release_check(gated):
    runs = [_run(OLDEST, "completed", "success", 1)]
    with (
        mock.patch.object(tested, "_read", side_effect=_github(runs)),
        mock.patch.object(lineage, "previous_release") as previous,
    ):
        tested.bind_tested_release_source("platform", "flow", None, OLDEST)

    previous.assert_not_called()


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
    assert "Omit both to bind the gate branch tip" in capsys.readouterr().err
