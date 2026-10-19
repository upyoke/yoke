"""``github_actions.run.cancel`` requests ordinary cancellation of one run."""

from __future__ import annotations

import pytest

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import github_actions_rest
from yoke_core.domain.gh_rest_transport import RestTransportError
from yoke_core.domain.handlers.github_actions_run_cancel import handle_run_cancel
from yoke_core.domain.project_github_auth import ProjectGithubAuth


def _request(repo: str = "upyoke/platform") -> FunctionCallRequest:
    return FunctionCallRequest(
        function="github_actions.run.cancel",
        actor=ActorContext(session_id="test-session"),
        target=TargetRef(kind="global"),
        payload={"repo": repo, "run_id": "123", "project": "platform"},
    )


@pytest.fixture(autouse=True)
def _auth(monkeypatch):
    monkeypatch.setattr(
        "yoke_core.domain.project_github_auth.resolve_project_github_auth",
        lambda project, **_: ProjectGithubAuth(
            project=project, repo="upyoke/platform", token="ghs_test"
        ),
    )


def test_cancel_posts_the_ordinary_cancel_endpoint(monkeypatch):
    posts = []
    monkeypatch.setattr(
        github_actions_rest,
        "rest_post",
        lambda path, **kwargs: posts.append((path, kwargs["token"])) or "",
    )

    outcome = handle_run_cancel(_request())

    assert outcome.primary_success
    assert outcome.result_payload["outcome"] == "cancel_requested"
    assert posts == [("/repos/upyoke/platform/actions/runs/123/cancel", "ghs_test")]


def test_a_run_that_already_finished_is_settled(monkeypatch):
    def _refuse(path, **_):
        raise RestTransportError("conflict", status=409)

    monkeypatch.setattr(github_actions_rest, "rest_post", _refuse)
    monkeypatch.setattr(
        github_actions_rest, "rest_get", lambda path, **_: {"status": "completed"}
    )

    outcome = handle_run_cancel(_request())

    assert outcome.primary_success
    assert outcome.result_payload["outcome"] == "already_completed"


def test_a_refusal_for_an_active_run_names_its_recovery(monkeypatch):
    def _refuse(path, **_):
        raise RestTransportError("forbidden", status=403)

    monkeypatch.setattr(github_actions_rest, "rest_post", _refuse)

    outcome = handle_run_cancel(_request())

    assert not outcome.primary_success
    assert outcome.error.code == "workflow_run_cancel_refused"
    assert "Recovery:" in outcome.error.message


def test_a_repository_outside_the_binding_is_refused(monkeypatch):
    monkeypatch.setattr(
        github_actions_rest,
        "rest_post",
        lambda *a, **k: pytest.fail("must not reach GitHub"),
    )

    outcome = handle_run_cancel(_request(repo="upyoke/yoke"))

    assert not outcome.primary_success
