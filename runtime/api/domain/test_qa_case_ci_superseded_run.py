"""Direct cancellation of the CI run replaced by a rebased gate."""

from __future__ import annotations

from contextlib import nullcontext

import pytest

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_ACTIONS_WRITE_PERMISSION_LEVELS,
)
from yoke_core.domain import qa_case_ci_superseded_run
from yoke_core.domain.gh_rest_transport import RestUnprocessableError
from yoke_core.domain.project_github_auth import ProjectGithubAuth


CURRENT_HEAD = "b" * 40
OLDER_HEAD = "a" * 40


@pytest.fixture(autouse=True)
def _machine_authority(monkeypatch):
    auth_calls = []
    monkeypatch.setattr(
        "yoke_cli.commands.merge_item_local_runtime.machine_github_user_authority",
        nullcontext,
    )

    def resolve(project, **kwargs):
        auth_calls.append((project, kwargs))
        return ProjectGithubAuth(
            project="yoke",
            repo="upyoke/yoke",
            token="ghu_test_token",
        )

    monkeypatch.setattr(
        "yoke_core.domain.project_github_auth.resolve_project_github_auth",
        resolve,
    )
    return auth_calls


def _runs(status: str):
    return {
        "workflow_runs": [
            {
                "id": 99,
                "head_branch": "YOK-9",
                "head_sha": CURRENT_HEAD,
                "status": "pending",
            },
            {
                "id": 88,
                "head_branch": "YOK-9",
                "head_sha": OLDER_HEAD,
                "status": status,
            },
        ]
    }


def _cancel():
    return qa_case_ci_superseded_run.force_cancel_if_rebased(
        project="yoke",
        repo="upyoke/yoke",
        workflow="yoke-ci.yml",
        branch="YOK-9",
        previous_head_sha=OLDER_HEAD,
        current_head_sha=CURRENT_HEAD,
    )


def test_active_prior_run_is_force_cancelled_and_recorded(
    monkeypatch,
    capsys,
    _machine_authority,
):
    posts = []

    def rest_get(path, *, query, token):
        assert path.endswith("/actions/workflows/yoke-ci.yml/runs")
        assert query == {
            "branch": "YOK-9",
            "event": "pull_request",
            "per_page": "10",
        }
        assert token == "ghu_test_token"
        return _runs("in_progress")

    def rest_post(path, *, body, token, max_attempts):
        posts.append((path, body, token, max_attempts))
        return ""

    monkeypatch.setattr(
        "yoke_core.domain.github_actions_rest.rest_get",
        rest_get,
    )
    monkeypatch.setattr(
        "yoke_core.domain.github_actions_rest.rest_post",
        rest_post,
    )

    assert _cancel() == "88"
    assert posts == [
        (
            "/repos/upyoke/yoke/actions/runs/88/force-cancel",
            {},
            "ghu_test_token",
            1,
        )
    ]
    assert _machine_authority == [
        (
            "yoke",
            {"required_permissions": GITHUB_ACTIONS_WRITE_PERMISSION_LEVELS},
        )
    ]
    assert "force-cancelled superseded run=88" in capsys.readouterr().err


def test_concluded_prior_run_is_a_no_op(monkeypatch):
    monkeypatch.setattr(
        "yoke_core.domain.github_actions_rest.rest_get",
        lambda *args, **kwargs: _runs("completed"),
    )
    monkeypatch.setattr(
        "yoke_core.domain.github_actions_rest.rest_post",
        pytest.fail,
    )

    assert _cancel() == ""


def test_cancel_race_that_concludes_is_a_no_op(monkeypatch):
    reads = iter((_runs("in_progress"), {"id": 88, "status": "completed"}))
    monkeypatch.setattr(
        "yoke_core.domain.github_actions_rest.rest_get",
        lambda *args, **kwargs: next(reads),
    )

    def raced(*args, **kwargs):
        raise RestUnprocessableError("run already completed", status=422)

    monkeypatch.setattr(
        "yoke_core.domain.github_actions_rest.rest_post",
        raced,
    )

    assert _cancel() == ""
