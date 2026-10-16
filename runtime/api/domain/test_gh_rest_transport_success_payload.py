"""Successful GitHub resource messages stay data through release tagging."""

from __future__ import annotations

import json

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import gh_rest_transport
from yoke_core.domain.handlers import github_commit_release_tag as github_release_tag


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


def test_commit_identity_uses_zero_graphql_pages_and_accepts_numeric_messages(
    monkeypatch,
):
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
                    "committer": {"date": "2026-10-14T09:41:59Z"},
                }
            )
        if "/git/ref/tags/" in path:
            import urllib.error

            raise urllib.error.HTTPError(request.full_url, 404, "missing", {}, None)
        if path == "/repos/upyoke/yoke/git/tags":
            return _Response(
                {
                    "sha": "c" * 40,
                    "message": (
                        "Yoke 0.2.0.202610140941\n\n"
                        "Automated hosted release for deployment run run-20260927-001."
                    ),
                },
                status=201,
            )
        if path == "/repos/upyoke/yoke/git/refs":
            return _Response({"ref": "refs/tags/0.2.0.202610140941"}, status=201)
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
        function="github.release.create_commit_tag",
        actor=ActorContext(actor_id="1", session_id="release-test"),
        target=TargetRef(kind="global", project_id="yoke"),
        payload={
            "repo": "upyoke/yoke",
            "project": "yoke",
            "source_sha": source_sha,
            "summary": "Release summary",
        },
    )

    outcome = github_release_tag.handle_create_commit_release_tag(request)

    assert outcome.primary_success is True
    assert outcome.result_payload["tag"] == "0.2.0.202610140941"
    assert outcome.result_payload["created"] is True
    assert sum(path == "/graphql" for path in paths) == 0
    assert paths == [
        f"/repos/upyoke/yoke/git/commits/{source_sha}",
        "/repos/upyoke/yoke/git/ref/tags/0.2.0.202610140941",
        "/repos/upyoke/yoke/git/tags",
        "/repos/upyoke/yoke/git/refs",
    ]
