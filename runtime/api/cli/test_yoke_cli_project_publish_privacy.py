"""Repository publishing preserves the requested privacy."""

from __future__ import annotations

import subprocess
from pathlib import Path

from yoke_cli.config import github_publish
from yoke_cli.config import project_publish_support as pub

from .project_publish_test_helpers import _local_git_transport  # noqa: F401


def test_create_and_publish_private_default_in_request() -> None:
    request = pub.PublishRequest(
        owner="octocat",
        name="widget",
        user_login="octocat",
        token="ghs_x",
    )
    assert request.private is True
    assert request.api_url == "https://api.github.com"


def test_create_repo_call_uses_request_private_flag(
    tmp_path: Path, monkeypatch
) -> None:
    bare = tmp_path / "remote.git"
    subprocess.run(
        ["git", "init", "--bare", str(bare)],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    checkout = tmp_path / "code"
    checkout.mkdir()
    monkeypatch.setattr(pub, "https_remote", lambda repo, **_: str(bare))
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Test")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "t@example.com")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "Test")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "t@example.com")

    seen: dict = {}

    def _fake_create(*args, **kwargs):
        seen.update(kwargs)
        return {"full_name": f"{kwargs['owner']}/{kwargs['name']}", "private": True}

    monkeypatch.setattr(github_publish, "create_repo", _fake_create)

    request = pub.PublishRequest(
        owner="acme-inc",
        name="thing",
        user_login="octocat",
        token="ghs_x",
        private=True,
    )
    pub.create_and_publish(checkout, request, default_branch="main")

    assert seen["owner"] == "acme-inc"
    assert seen["name"] == "thing"
    assert seen["user_login"] == "octocat"
    assert seen["private"] is True
