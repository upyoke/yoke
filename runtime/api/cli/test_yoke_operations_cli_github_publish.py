"""REST contract for the GitHub publish boundary (owner list + repo create).

The network is mocked at the ``urllib.request.urlopen`` seam so no scenario
hits GitHub. Owner-list parsing leads with the authenticated user and appends
orgs; repo creation defaults to private and routes user vs org to the right
endpoint with the right JSON body.
"""

from __future__ import annotations

import io
import json
from typing import Any

import pytest

from yoke_cli.config import github_publish
from yoke_cli.config import github_publish_transport


class _FakeResponse(io.BytesIO):
    """A urlopen context manager returning canned JSON bytes."""

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc: Any) -> bool:
        return False


class _Recorder:
    """Captures each request and replays a queued JSON response by path."""

    def __init__(self, responses: dict[str, Any]) -> None:
        self._responses = responses
        self.requests: list[dict[str, Any]] = []

    def __call__(self, request, timeout: float = 0.0) -> _FakeResponse:
        body = request.data.decode("utf-8") if request.data else None
        self.requests.append({
            "url": request.full_url,
            "method": request.get_method(),
            "body": json.loads(body) if body else None,
        })
        url_path = request.full_url.split("?", 1)[0]
        for path, payload in self._responses.items():
            if url_path.endswith(path):
                return _FakeResponse(json.dumps(payload).encode("utf-8"))
        raise AssertionError(f"no canned response for {request.full_url}")


def _install(monkeypatch, recorder: _Recorder) -> None:
    monkeypatch.setattr(github_publish_transport, "_urlopen", recorder)


def test_list_repo_owners_leads_with_user_then_orgs(monkeypatch) -> None:
    recorder = _Recorder({
        "/user": {"login": "octocat", "id": 1},
        "/user/orgs": [{"login": "acme-inc"}, {"login": "side-project-co"}],
    })
    _install(monkeypatch, recorder)

    owners = github_publish.list_repo_owners("https://api.github.com", "ghs_x")

    assert [o.login for o in owners] == ["octocat", "acme-inc", "side-project-co"]
    assert owners[0].kind == "user"
    assert owners[1].kind == "organization"
    assert owners[2].kind == "organization"


def test_list_repo_owners_tolerates_no_orgs(monkeypatch) -> None:
    recorder = _Recorder({
        "/user": {"login": "solo", "id": 7},
        "/user/orgs": [],
    })
    _install(monkeypatch, recorder)

    owners = github_publish.list_repo_owners("https://api.github.com", "ghs_x")

    assert [o.login for o in owners] == ["solo"]
    assert owners[0].kind == "user"


def test_list_repo_owners_requires_a_login(monkeypatch) -> None:
    recorder = _Recorder({"/user": {"id": 1}})
    _install(monkeypatch, recorder)

    with pytest.raises(github_publish.GitHubPublishError):
        github_publish.list_repo_owners("https://api.github.com", "ghs_x")


def test_create_repo_for_user_posts_to_user_repos_private(monkeypatch) -> None:
    recorder = _Recorder({
        "/user/repos": {
            "full_name": "octocat/widget",
            "private": True,
            "clone_url": "https://github.com/octocat/widget.git",
            "ssh_url": "git@github.com:octocat/widget.git",
            "default_branch": "main",
        },
    })
    _install(monkeypatch, recorder)

    created = github_publish.create_repo(
        "https://api.github.com", "ghs_x",
        owner="octocat", name="widget", user_login="octocat",
        administration_allowed=True,
    )

    assert created["full_name"] == "octocat/widget"
    assert created["private"] is True
    req = recorder.requests[-1]
    assert req["url"].endswith("/user/repos")
    assert req["method"] == "POST"
    assert req["body"] == {"name": "widget", "private": True}


def test_create_repo_requires_optional_administration_without_network(monkeypatch) -> None:
    recorder = _Recorder({})
    _install(monkeypatch, recorder)

    with pytest.raises(github_publish.GitHubPublishError) as caught:
        github_publish.create_repo(
            "https://api.github.com", "ghu_short_lived",
            owner="octocat", name="widget", user_login="octocat",
        )

    assert "optional GitHub App Administration permission" in str(caught.value)
    assert "https://github.com/new" in str(caught.value)
    assert recorder.requests == []


def test_create_repo_ghes_guidance_never_links_public_github(monkeypatch) -> None:
    recorder = _Recorder({})
    _install(monkeypatch, recorder)

    with pytest.raises(github_publish.GitHubPublishError) as caught:
        github_publish.create_repo(
            "https://ghe.example/api/v3", "ghu_short_lived",
            owner="octocat", name="widget", user_login="octocat",
            web_url="https://ghe.example",
        )

    message = str(caught.value)
    assert "https://ghe.example/new" in message
    assert "https://github.com" not in message
    assert recorder.requests == []


def test_create_repo_for_org_posts_to_org_repos(monkeypatch) -> None:
    recorder = _Recorder({
        "/orgs/acme-inc/repos": {"full_name": "acme-inc/widget", "private": True},
    })
    _install(monkeypatch, recorder)

    created = github_publish.create_repo(
        "https://api.github.com", "ghs_x",
        owner="acme-inc", name="widget", user_login="octocat",
        administration_allowed=True,
    )

    assert created["full_name"] == "acme-inc/widget"
    req = recorder.requests[-1]
    assert req["url"].endswith("/orgs/acme-inc/repos")
    assert req["method"] == "POST"
    assert req["body"] == {"name": "widget", "private": True}


def test_create_repo_public_when_private_false(monkeypatch) -> None:
    recorder = _Recorder({
        "/user/repos": {"full_name": "octocat/open", "private": False},
    })
    _install(monkeypatch, recorder)

    github_publish.create_repo(
        "https://api.github.com", "ghs_x",
        owner="octocat", name="open", user_login="octocat", private=False,
        administration_allowed=True,
    )

    assert recorder.requests[-1]["body"] == {"name": "open", "private": False}


def test_create_repo_requires_full_name(monkeypatch) -> None:
    recorder = _Recorder({"/user/repos": {"private": True}})
    _install(monkeypatch, recorder)

    with pytest.raises(github_publish.GitHubPublishError):
        github_publish.create_repo(
            "https://api.github.com", "ghs_x",
            owner="octocat", name="widget", user_login="octocat",
            administration_allowed=True,
        )


def test_create_repo_happy_path_makes_no_extra_calls(monkeypatch) -> None:
    # The 2xx create path must not GET the repo or probe commits — the extra
    # round-trips only happen on the 422 resume branch.
    recorder = _Recorder({
        "/user/repos": {"full_name": "octocat/widget", "private": True},
    })
    _install(monkeypatch, recorder)

    github_publish.create_repo(
        "https://api.github.com", "ghs_x",
        owner="octocat", name="widget", user_login="octocat",
        administration_allowed=True,
    )

    assert len(recorder.requests) == 1
    assert recorder.requests[0]["method"] == "POST"


def test_fork_repo_posts_to_forks_endpoint(monkeypatch) -> None:
    recorder = _Recorder({
        "/repos/acme/widgets/forks": {
            "full_name": "octocat/widgets",
            "private": False,
            "clone_url": "https://github.com/octocat/widgets.git",
            "ssh_url": "git@github.com:octocat/widgets.git",
            "default_branch": "main",
        },
    })
    _install(monkeypatch, recorder)

    fork = github_publish.fork_repo(
        "https://api.github.com", "ghs_x", owner="acme", repo="widgets",
    )

    assert fork["full_name"] == "octocat/widgets"
    assert fork["ssh_url"] == "git@github.com:octocat/widgets.git"
    req = recorder.requests[-1]
    assert req["url"].endswith("/repos/acme/widgets/forks")
    assert req["method"] == "POST"


def test_fork_repo_requires_full_name(monkeypatch) -> None:
    recorder = _Recorder({"/repos/acme/widgets/forks": {"private": False}})
    _install(monkeypatch, recorder)

    with pytest.raises(github_publish.GitHubPublishError):
        github_publish.fork_repo(
            "https://api.github.com", "ghs_x", owner="acme", repo="widgets",
        )
