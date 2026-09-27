"""Successful GitHub resource messages stay data through release tagging."""

from __future__ import annotations

import json

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import gh_rest_transport
from yoke_core.domain.handlers import github_release_tag


class _Response:
    def __init__(self, payload: dict, status: int = 200):
        self.status = status
        self.headers = {"Content-Type": "application/json"}
        self.body = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, size: int = -1) -> bytes:
        return self.body if size < 0 else self.body[:size]


def test_release_tag_accepts_source_commit_message_with_pull_number(monkeypatch):
    source_sha = "a" * 40
    paths = []

    def open_github(request, timeout):
        path = request.full_url.removeprefix("https://api.github.com")
        paths.append(path)
        if path == f"/repos/upyoke/yoke/git/commits/{source_sha}":
            return _Response(
                {
                    "sha": source_sha,
                    "message": "Merge pull request #1500 from upyoke/example",
                }
            )
        if path == "/graphql":
            return _Response(
                {
                    "data": {
                        "repository": {
                            "refs": {
                                "nodes": [
                                    {
                                        "name": "v0.1.1+launch.41",
                                        "target": {
                                            "__typename": "Tag",
                                            "target": {
                                                "__typename": "Commit",
                                                "oid": "b" * 40,
                                            },
                                        },
                                    }
                                ],
                                "pageInfo": {"hasNextPage": False, "endCursor": None},
                            }
                        }
                    }
                }
            )
        if path == "/repos/upyoke/yoke/git/tags":
            return _Response({"sha": "c" * 40}, status=201)
        if path == "/repos/upyoke/yoke/git/refs":
            return _Response({"ref": "refs/tags/v0.1.1+launch.42"}, status=201)
        raise AssertionError(path)

    monkeypatch.setattr(gh_rest_transport, "urlopen", open_github)
    monkeypatch.delenv(gh_rest_transport._FAKE_DIR_ENV, raising=False)
    monkeypatch.setattr(
        github_release_tag,
        "_validate_and_resolve",
        lambda request, model, function_id, required_permissions: (
            model.model_validate(request.payload),
            "installation-token",
            None,
        ),
    )
    request = FunctionCallRequest(
        function="github.release.create_next_tag",
        actor=ActorContext(actor_id="1", session_id="release-test"),
        target=TargetRef(kind="global", project_id="yoke"),
        payload={
            "repo": "upyoke/yoke",
            "project": "yoke",
            "source_sha": source_sha,
            "summary": "Release summary",
        },
    )

    outcome = github_release_tag.handle_create_next_release_tag(request)

    assert outcome.primary_success is True
    assert outcome.result_payload["tag"] == "v0.1.1+launch.42"
    assert outcome.result_payload["created"] is True
    assert paths == [
        f"/repos/upyoke/yoke/git/commits/{source_sha}",
        "/graphql",
        "/repos/upyoke/yoke/git/tags",
        "/repos/upyoke/yoke/git/refs",
    ]
