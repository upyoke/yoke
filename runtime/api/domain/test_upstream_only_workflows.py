"""Upstream governance and hosted jobs skip in forks and other copies."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_core.domain.yaml_helper import load_document

WORKFLOWS = Path(__file__).resolve().parents[3] / ".github/workflows"
UPSTREAM = "upyoke/yoke"


def _condition(workflow, job):
    return load_document(WORKFLOWS / workflow)["jobs"][job]["if"]


def _runs(condition, repository, event_name, comment="", pull_request=False):
    github = SimpleNamespace(
        repository=repository,
        event_name=event_name,
        event=SimpleNamespace(
            issue=SimpleNamespace(pull_request=pull_request),
            comment=SimpleNamespace(body=comment),
        ),
    )
    expression = (
        " ".join(condition.split()).replace("&&", " and ").replace("||", " or ")
    )
    return bool(eval(expression, {"__builtins__": {}}, {"github": github}))


@pytest.mark.parametrize("repository", [UPSTREAM, "fork-owner/yoke", "team/copy"])
@pytest.mark.parametrize(
    "workflow,job",
    [
        ("platform-release-bridge.yml", "dispatch-platform-release"),
        ("consumer-compatibility-advisory.yml", "advisory"),
        ("yoke-ci.yml", "consumer_advisory"),
    ],
)
def test_hosted_jobs_run_only_in_upstream(repository, workflow, job):
    assert _runs(_condition(workflow, job), repository, "workflow_dispatch") == (
        repository == UPSTREAM
    )


@pytest.mark.parametrize("repository", [UPSTREAM, "fork-owner/yoke", "team/copy"])
@pytest.mark.parametrize(
    "event,comment,is_pr,expected",
    [
        ("pull_request_target", "", False, True),
        ("issue_comment", "recheck", True, True),
        (
            "issue_comment",
            "I have read the CLA Document and I hereby sign the CLA",
            True,
            True,
        ),
        ("issue_comment", "recheck", False, False),
        ("issue_comment", "unrelated", True, False),
        ("merge_group", "", False, False),
    ],
)
def test_cla_guard_preserves_upstream_event_filters(
    repository, event, comment, is_pr, expected
):
    assert _runs(
        _condition("cla.yml", "signature-check"), repository, event, comment, is_pr
    ) == (expected and repository == UPSTREAM)


@pytest.mark.parametrize("repository", [UPSTREAM, "fork-owner/yoke", "team/copy"])
@pytest.mark.parametrize(
    "event", ["merge_group", "pull_request_target", "issue_comment"]
)
def test_cla_train_pass_through_runs_only_for_upstream_trains(repository, event):
    assert _runs(_condition("cla.yml", "train-pass-through"), repository, event) == (
        repository == UPSTREAM and event == "merge_group"
    )
