"""Recovery for accepted GitHub forks whose POST response was lost."""

from __future__ import annotations

import pytest

from yoke_cli.config import github_publish


def _error(message: str, *, status: int | None = None):
    return github_publish.GitHubPublishError(message, status=status)


def test_lost_fork_response_is_adopted_on_exact_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    post_attempts = 0
    reconciliation_round = 0
    clock = [0.0]

    def request(api_url, path, token, *, method="GET", **kwargs):
        nonlocal post_attempts, reconciliation_round
        if method == "POST":
            post_attempts += 1
            reconciliation_round = post_attempts
            if post_attempts == 1:
                raise _error("response deadline")
            raise _error("fork already exists", status=422)
        if path == "/user":
            return {"login": "octocat"}
        if path == "/repos/octocat/widgets":
            if reconciliation_round == 1:
                raise _error("not visible", status=404)
            return {
                "full_name": "octocat/widgets",
                "fork": True,
                "parent": {
                    "full_name": "acme/widgets", "private": False,
                },
                "private": False,
            }
        raise AssertionError(path)

    monkeypatch.setattr(github_publish, "_request_json", request)

    def sleep(seconds: float) -> None:
        clock[0] += seconds

    with pytest.raises(
        github_publish.GitHubPublishError,
        match="did not become readable",
    ):
        github_publish.fork_repo(
            "https://api.github.com", "token", owner="acme", repo="widgets",
            sleep=sleep, monotonic=lambda: clock[0],
        )

    fork = github_publish.fork_repo(
        "https://api.github.com", "token", owner="acme", repo="widgets",
        sleep=sleep, monotonic=lambda: clock[0],
    )

    assert post_attempts == 2
    assert fork["full_name"] == "octocat/widgets"
    assert fork["reused"] is True


@pytest.mark.parametrize("candidate", [
    {
        "full_name": "octocat/widgets",
        "fork": False,
        "parent": {"full_name": "acme/widgets", "private": False},
        "private": False,
    },
    {
        "full_name": "octocat/widgets",
        "fork": True,
        "parent": {"full_name": "other/widgets", "private": False},
        "private": False,
    },
])
def test_wrong_existing_repository_is_never_adopted(
    monkeypatch: pytest.MonkeyPatch,
    candidate: dict,
) -> None:
    def request(api_url, path, token, *, method="GET", **kwargs):
        if method == "POST":
            raise _error("fork already exists", status=422)
        if path == "/user":
            return {"login": "octocat"}
        if path == "/repos/octocat/widgets":
            return candidate
        raise AssertionError(path)

    monkeypatch.setattr(github_publish, "_request_json", request)
    with pytest.raises(
        github_publish.GitHubPublishError,
        match="not the exact fork",
    ):
        github_publish.fork_repo(
            "https://api.github.com", "token", owner="acme", repo="widgets",
            sleep=lambda seconds: None, monotonic=lambda: 0,
        )


@pytest.mark.parametrize("candidate", [
    {
        "full_name": "octocat/widgets", "fork": True, "private": False,
        "parent": {"full_name": "acme/widgets"},
    },
    {
        "full_name": "octocat/widgets", "fork": True,
        "parent": {"full_name": "acme/widgets", "private": False},
    },
    {
        "full_name": "octocat/widgets", "fork": True, "private": False,
        "parent": {"full_name": "acme/widgets", "private": True},
    },
    {
        "full_name": "octocat/widgets", "fork": True, "private": True,
        "parent": {"full_name": "acme/widgets", "private": False},
    },
    {
        "full_name": "octocat/widgets", "fork": True, "private": 1,
        "parent": {"full_name": "acme/widgets", "private": True},
    },
])
def test_fork_visibility_must_be_present_and_match_source(
    monkeypatch: pytest.MonkeyPatch, candidate: dict,
) -> None:
    def request(api_url, path, token, *, method="GET", **kwargs):
        if path == "/user":
            return {"login": "octocat"}
        if method == "POST":
            return candidate
        raise AssertionError(path)

    monkeypatch.setattr(github_publish, "_request_json", request)
    with pytest.raises(github_publish.GitHubPublishError, match="exact fork"):
        github_publish.fork_repo(
            "https://api.github.com", "token", owner="acme", repo="widgets",
            sleep=lambda seconds: None, monotonic=lambda: 0,
        )
