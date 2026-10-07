"""Create-only dispatch tag on a deployment run's release commit."""

from __future__ import annotations

import pytest

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.gh_rest_transport_errors import RestUnprocessableError
from yoke_core.domain.handlers import github_actions_dispatch_tag as subject


SHA = "a" * 40
OTHER_SHA = "b" * 40
TAG = subject.dispatch_tag_name("run-20261007-021")


def _request(**overrides) -> FunctionCallRequest:
    payload = {"repo": "owner/app", "project": "app", "tag": TAG, "sha": SHA}
    payload.update(overrides)
    return FunctionCallRequest(
        function=subject.FUNCTION_ID,
        actor=ActorContext(actor_id="1", session_id="dispatch-tag-test"),
        target=TargetRef(kind="global", project_id="app"),
        payload=payload,
    )


def _install(monkeypatch, *, refs: dict, commits: set[str], race: str = ""):
    """Fake GitHub: ``refs`` maps tag -> commit, ``commits`` the repo holds."""
    posts: list[dict] = []
    monkeypatch.setattr(
        subject,
        "_validate_and_resolve",
        lambda request, model, function_id, required_permissions: (
            model.model_validate(request.payload), "installation-token", None,
        ),
    )

    def rest_get(path, *, token):
        if "/git/ref/tags/" in path:
            sha = refs.get(path.split("/git/ref/tags/", 1)[1])
            return None if sha is None else {"object": {"type": "commit", "sha": sha}}
        sha = path.rsplit("/", 1)[1]
        return {"sha": sha} if sha in commits else None

    def rest_post(path, *, body, token, max_attempts):
        posts.append(body)
        if race:
            refs[TAG] = race
            raise RestUnprocessableError("Reference already exists")
        refs[body["ref"].removeprefix("refs/tags/")] = body["sha"]

    monkeypatch.setattr(subject, "rest_get", rest_get)
    monkeypatch.setattr(subject, "rest_post", rest_post)
    return posts


def test_creates_the_run_tag_on_the_release_commit(monkeypatch) -> None:
    posts = _install(monkeypatch, refs={}, commits={SHA})

    outcome = subject.handle_dispatch_tag_ensure(_request())

    assert outcome.primary_success is True
    assert outcome.result_payload["created"] is True
    assert posts == [{"ref": f"refs/tags/{TAG}", "sha": SHA}]


def test_an_existing_tag_on_the_same_commit_is_reused(monkeypatch) -> None:
    posts = _install(monkeypatch, refs={TAG: SHA}, commits={SHA})

    outcome = subject.handle_dispatch_tag_ensure(_request())

    assert outcome.primary_success is True
    assert outcome.result_payload["created"] is False
    assert posts == []


def test_an_existing_tag_on_another_commit_is_refused_not_moved(monkeypatch) -> None:
    posts = _install(monkeypatch, refs={TAG: OTHER_SHA}, commits={SHA})

    outcome = subject.handle_dispatch_tag_ensure(_request())

    assert outcome.primary_success is False
    assert outcome.error.code == "dispatch_tag_conflict"
    assert OTHER_SHA in outcome.error.message and "never moves" in outcome.error.message
    assert posts == []


def test_a_commit_the_repository_lacks_is_refused(monkeypatch) -> None:
    posts = _install(monkeypatch, refs={}, commits=set())

    outcome = subject.handle_dispatch_tag_ensure(_request())

    assert outcome.error.code == "dispatch_tag_commit_missing"
    assert posts == []


@pytest.mark.parametrize("winner,created_ok", [(SHA, True), (OTHER_SHA, False)])
def test_a_concurrent_create_settles_on_what_it_wrote(
    monkeypatch, winner, created_ok
) -> None:
    _install(monkeypatch, refs={}, commits={SHA}, race=winner)

    outcome = subject.handle_dispatch_tag_ensure(_request())

    assert outcome.primary_success is created_ok
    if created_ok:
        assert outcome.result_payload["created"] is False
    else:
        assert outcome.error.code == "dispatch_tag_conflict"


@pytest.mark.parametrize("tag", ["v1.2.3", "refs/tags/yoke-deploy/x", "yoke-deploy/"])
def test_tags_outside_the_dispatch_namespace_are_rejected(tag) -> None:
    with pytest.raises(ValueError):
        subject.DispatchTagEnsureRequest.model_validate(
            {"repo": "owner/app", "project": "app", "tag": tag, "sha": SHA}
        )
