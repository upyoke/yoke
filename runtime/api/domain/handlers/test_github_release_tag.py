"""Immutable annotated release-tag handler contracts."""

from __future__ import annotations

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.gh_rest_transport_errors import RestUnprocessableError
from yoke_core.domain.handlers import github_release_tag as subject


SOURCE_SHA = "a" * 40
TAG_40_OBJECT = "b" * 40
TAG_41_OBJECT = "c" * 40
CREATED_TAG_OBJECT = "d" * 40


def _request() -> FunctionCallRequest:
    return FunctionCallRequest(
        function="github.release.create_next_tag",
        actor=ActorContext(actor_id="1", session_id="release-test"),
        target=TargetRef(kind="global", project_id="yoke"),
        payload={
            "repo": "upyoke/yoke",
            "project": "yoke",
            "source_sha": SOURCE_SHA,
            "summary": "Ships the merged item through the hosted train.",
        },
    )


def _ref(tag: str, tag_object_sha: str) -> dict:
    return {
        "ref": f"refs/tags/{tag}",
        "object": {"type": "tag", "sha": tag_object_sha},
    }


def _install_auth(monkeypatch) -> None:
    monkeypatch.setattr(
        subject,
        "_validate_and_resolve",
        lambda request, model, function_id, required_permissions: (
            model.model_validate(request.payload),
            "installation-token",
            None,
        ),
    )


def test_creates_the_next_annotated_launch_tag(monkeypatch) -> None:
    _install_auth(monkeypatch)
    refs = [
        _ref("v0.1.1+launch.40", TAG_40_OBJECT),
        _ref("v0.1.1+launch.41", TAG_41_OBJECT),
    ]

    def fake_get(path: str, *, token: str):
        assert token == "installation-token"
        if "/git/commits/" in path:
            return {"sha": SOURCE_SHA}
        if "/matching-refs/tags/v?" in path:
            assert "per_page=100&page=1" in path
            return refs
        if path.endswith(TAG_40_OBJECT):
            return {"object": {"type": "commit", "sha": "1" * 40}}
        if path.endswith(TAG_41_OBJECT):
            return {"object": {"type": "commit", "sha": "2" * 40}}
        raise AssertionError(path)

    posts = []

    def fake_post(path: str, *, body: dict, token: str, max_attempts: int):
        posts.append((path, body, token, max_attempts))
        if path.endswith("/git/tags"):
            return {"sha": CREATED_TAG_OBJECT}
        return {"ref": body["ref"]}

    monkeypatch.setattr(subject, "rest_get", fake_get)
    monkeypatch.setattr(subject, "rest_post", fake_post)

    outcome = subject.handle_create_next_release_tag(_request())

    assert outcome.primary_success is True
    assert outcome.result_payload == {
        "tag": "v0.1.1+launch.42",
        "version": "0.1.1+launch.42",
        "source_sha": SOURCE_SHA,
        "created": True,
    }
    assert posts[0][1] == {
        "tag": "v0.1.1+launch.42",
        "message": (
            "Yoke 0.1.1+launch.42\n\n"
            "Ships the merged item through the hosted train."
        ),
        "object": SOURCE_SHA,
        "type": "commit",
    }
    assert posts[1][1] == {
        "ref": "refs/tags/v0.1.1+launch.42",
        "sha": CREATED_TAG_OBJECT,
    }


def test_retry_returns_the_existing_annotated_tag(monkeypatch) -> None:
    _install_auth(monkeypatch)
    refs = [_ref("v0.1.1+launch.41", TAG_41_OBJECT)]
    monkeypatch.setattr(
        subject,
        "rest_get",
        lambda path, *, token: (
            {"sha": SOURCE_SHA}
            if "/git/commits/" in path
            else refs
            if "/matching-refs/tags/v?" in path
            else {"object": {"type": "commit", "sha": SOURCE_SHA}}
        ),
    )
    monkeypatch.setattr(
        subject,
        "rest_post",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("idempotent retry must not create another tag")
        ),
    )

    outcome = subject.handle_create_next_release_tag(_request())

    assert outcome.primary_success is True
    assert outcome.result_payload["tag"] == "v0.1.1+launch.41"
    assert outcome.result_payload["created"] is False


def test_ref_race_reloads_inventory_and_advances_again(monkeypatch) -> None:
    _install_auth(monkeypatch)
    inventories = iter([
        [_ref("v0.1.1+launch.41", TAG_41_OBJECT)],
        [
            _ref("v0.1.1+launch.41", TAG_41_OBJECT),
            _ref("v0.1.1+launch.42", "e" * 40),
        ],
    ])

    def fake_get(path: str, *, token: str):
        if "/git/commits/" in path:
            return {"sha": SOURCE_SHA}
        if "/matching-refs/tags/v?" in path:
            return next(inventories)
        return {"object": {"type": "commit", "sha": "9" * 40}}

    created_tags = []

    def fake_post(path: str, *, body: dict, token: str, max_attempts: int):
        if path.endswith("/git/tags"):
            created_tags.append(body["tag"])
            return {"sha": CREATED_TAG_OBJECT}
        if len(created_tags) == 1:
            raise RestUnprocessableError("Reference already exists", status=422)
        return {"ref": body["ref"]}

    monkeypatch.setattr(subject, "rest_get", fake_get)
    monkeypatch.setattr(subject, "rest_post", fake_post)

    outcome = subject.handle_create_next_release_tag(_request())

    assert outcome.primary_success is True
    assert outcome.result_payload["tag"] == "v0.1.1+launch.43"
    assert created_tags == ["v0.1.1+launch.42", "v0.1.1+launch.43"]


def test_rejects_a_missing_source_commit(monkeypatch) -> None:
    _install_auth(monkeypatch)
    monkeypatch.setattr(
        subject,
        "rest_get",
        lambda path, *, token: {"sha": ""},
    )

    outcome = subject.handle_create_next_release_tag(_request())

    assert outcome.primary_success is False
    assert outcome.error is not None
    assert outcome.error.code == "release_tag_invalid"
    assert "does not exist in the project repository" in outcome.error.message
