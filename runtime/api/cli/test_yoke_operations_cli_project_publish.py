"""Git-side publish helpers: init-if-needed, remote detection, create+push.

These exercise the real git operations against local temp repos (a bare repo
stands in for the GitHub remote) while the GitHub REST create is mocked at the
``github_publish.create_repo`` seam. No network, no live GitHub.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from yoke_cli.config import github_publish
from yoke_cli.config import project_publish_support as pub
from yoke_cli.config.project_onboard_support import ProjectOnboardError


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def _init_repo(root: Path, branch: str = "main") -> None:
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "--initial-branch", branch)
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "Test")


@pytest.fixture(autouse=True)
def _local_git_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        pub,
        "run_git",
        lambda root, *args, **_kwargs: _git(root, *args),
    )


def test_is_git_repo_distinguishes_plain_folder(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    assert pub.is_git_repo(plain) is False

    repo = tmp_path / "repo"
    _init_repo(repo)
    assert pub.is_git_repo(repo) is True


def test_has_remote_false_on_plain_and_remoteless_repo(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    assert pub.has_remote(plain) is False

    repo = tmp_path / "repo"
    _init_repo(repo)
    assert pub.has_remote(repo) is False


def test_has_remote_true_once_origin_added(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _git(repo, "remote", "add", "origin", "git@github.com:owner/repo.git")
    assert pub.has_remote(repo) is True


def test_init_repo_if_needed_only_inits_plain_folder(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    assert pub.init_repo_if_needed(plain, "main") is True
    assert pub.is_git_repo(plain) is True

    # Second call is a no-op on the now-initialized repo.
    assert pub.init_repo_if_needed(plain, "main") is False


def test_ensure_initial_commit_creates_commit_only_when_unborn(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "file.txt").write_text("hello\n", encoding="utf-8")

    pub.ensure_initial_commit(repo, "main")
    head = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"], cwd=repo,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    assert head.returncode == 0
    first = head.stdout.decode().strip()

    # A second call with an existing HEAD must not add another commit.
    pub.ensure_initial_commit(repo, "main")
    head2 = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"], cwd=repo,
        stdout=subprocess.PIPE,
    )
    assert head2.stdout.decode().strip() == first


def test_create_and_publish_inits_commits_and_pushes(tmp_path: Path, monkeypatch) -> None:
    # A bare repo stands in for the GitHub remote; the https_remote builder is
    # redirected to it so the real push lands locally without an SSH host-key
    # prompt or any git@github.com transport.
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(bare)], check=True,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    checkout = tmp_path / "code" / "widget"
    checkout.mkdir(parents=True)
    (checkout / "README.md").write_text("# widget\n", encoding="utf-8")

    monkeypatch.setattr(
        github_publish, "create_repo",
        lambda *a, **k: {"full_name": "octocat/widget", "private": True},
    )
    monkeypatch.setattr(pub, "https_remote", lambda repo, **_: str(bare))
    # git identity for the auto-created commit (CI envs may lack a global one).
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Test")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "t@example.com")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "Test")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "t@example.com")

    token = "ghs_publish_secret_token"
    request = pub.PublishRequest(
        owner="octocat", name="widget", user_login="octocat", token=token,
    )
    created = pub.create_and_publish(checkout, request, default_branch="main")

    assert created["full_name"] == "octocat/widget"
    assert pub.is_git_repo(checkout) is True
    assert pub.has_remote(checkout) is True
    # The bare remote now has the pushed default branch.
    branches = subprocess.run(
        ["git", "branch", "--list"], cwd=bare,
        stdout=subprocess.PIPE, text=True, check=True,
    )
    assert "main" in branches.stdout
    # SECURITY: the push carried the token only as a request-scoped header — it
    # must never persist in the checkout's config or the stored origin URL.
    config_text = (checkout / ".git" / "config").read_text(encoding="utf-8")
    assert token not in config_text
    assert "extraheader" not in config_text


def test_create_and_publish_denied_push_raises_typed_naming_error(
    tmp_path: Path, monkeypatch
) -> None:
    """A denied push after a successful create raises a repo-naming typed error.

    A repository-scoped selected-repositories GitHub App auth POSTs the repo OK then the push is
    refused with a 403. The seam converts that raw ProjectOnboardError into a
    friendly GitHubPublishError that names the orphaned repo to delete.
    """
    checkout = tmp_path / "code"
    checkout.mkdir()

    monkeypatch.setattr(
        github_publish, "create_repo",
        lambda *a, **k: {"full_name": "octocat/widget", "private": True},
    )
    monkeypatch.setattr(pub, "init_repo_if_needed", lambda root, branch: True)
    monkeypatch.setattr(pub, "ensure_initial_commit", lambda root, branch: None)
    monkeypatch.setattr(pub, "local_head_sha", lambda root, branch: "abc123")

    def _denied_push(*a, **k):
        raise ProjectOnboardError(
            "git push -u origin main failed with 128: "
            "remote: Write access to repository not granted."
        )

    monkeypatch.setattr(pub, "publish_to_remote", _denied_push)

    request = pub.PublishRequest(
        owner="octocat", name="widget", user_login="octocat", token="ghs_x",
    )
    with pytest.raises(pub.GitHubPublishError) as excinfo:
        pub.create_and_publish(checkout, request, default_branch="main")
    message = str(excinfo.value)
    assert "octocat/widget" in message  # names the orphaned repo
    assert "delete it" in message.lower()


def test_create_and_publish_non_403_push_error_names_repo_and_resume(
    tmp_path: Path, monkeypatch
) -> None:
    """A non-permission push failure reports the created repo and resume path."""
    checkout = tmp_path / "code"
    checkout.mkdir()

    monkeypatch.setattr(
        github_publish, "create_repo",
        lambda *a, **k: {"full_name": "octocat/widget", "private": True},
    )
    monkeypatch.setattr(pub, "init_repo_if_needed", lambda root, branch: True)
    monkeypatch.setattr(pub, "ensure_initial_commit", lambda root, branch: None)
    monkeypatch.setattr(pub, "local_head_sha", lambda root, branch: "abc123")

    def _network_push(*a, **k):
        raise ProjectOnboardError(
            "git push -u origin main failed with 128: "
            "fatal: unable to access 'https://github.com/...': Could not resolve host"
        )

    monkeypatch.setattr(pub, "publish_to_remote", _network_push)

    request = pub.PublishRequest(
        owner="octocat", name="widget", user_login="octocat", token="ghs_x",
    )
    with pytest.raises(pub.GitHubPublishError) as excinfo:
        pub.create_and_publish(checkout, request, default_branch="main")
    message = str(excinfo.value)
    assert "octocat/widget" in message
    assert "Could not resolve host" in message
    assert "re-run yoke onboard to resume the push" in message


def test_create_and_publish_retries_push_when_origin_already_matches(
    tmp_path: Path, monkeypatch
) -> None:
    """A retry after remote-add-but-before-push reuses origin and pushes."""
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(bare)], check=True,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    checkout = tmp_path / "code"
    _init_repo(checkout)
    (checkout / "README.md").write_text("# widget\n", encoding="utf-8")
    _git(checkout, "add", "-A")
    _git(checkout, "commit", "-m", "Initial")
    _git(checkout, "remote", "add", "origin", str(bare))

    create_calls = {"count": 0}
    monkeypatch.setattr(
        github_publish, "create_repo",
        lambda *a, **k: create_calls.__setitem__(
            "count", create_calls["count"] + 1,
        ),
    )
    monkeypatch.setattr(pub, "https_remote", lambda repo, **_: str(bare))
    monkeypatch.setattr(
        github_publish,
        "verify_resumable_repo",
        lambda *args, **kwargs: {
            "full_name": "octocat/widget", "private": True, "reused": True,
        },
    )

    request = pub.PublishRequest(
        owner="octocat", name="widget", user_login="octocat", token="ghs_x",
    )
    created = pub.create_and_publish(checkout, request, default_branch="main")

    assert created["full_name"] == "octocat/widget"
    assert created["reused"] is True
    assert create_calls["count"] == 0
    branches = subprocess.run(
        ["git", "branch", "--list"], cwd=bare,
        stdout=subprocess.PIPE, text=True, check=True,
    )
    assert "main" in branches.stdout


def test_publish_origin_mismatch_never_echoes_embedded_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    secret = "ghp_publish_origin_secret"
    monkeypatch.setattr(
        pub.project_clone_resume,
        "remote_url",
        lambda *_args: (
            f"https://octocat:{secret}@github.com/foreign/repository.git"
        ),
    )
    monkeypatch.setattr(
        pub.project_clone_resume,
        "same_repo",
        lambda *_args, **_kwargs: False,
    )

    with pytest.raises(ProjectOnboardError) as caught:
        pub.publish_to_remote(
            checkout,
            github_repo="owner/demo",
            default_branch="main",
            web_url="https://github.com",
        )

    assert secret not in str(caught.value)
    assert "different origin" in str(caught.value)


def test_create_and_publish_private_default_in_request() -> None:
    request = pub.PublishRequest(
        owner="octocat", name="widget", user_login="octocat", token="ghs_x",
    )
    assert request.private is True
    assert request.api_url == "https://api.github.com"


def test_create_repo_call_uses_request_private_flag(tmp_path: Path, monkeypatch) -> None:
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(bare)], check=True,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
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
        owner="acme-inc", name="thing", user_login="octocat", token="ghs_x",
        private=True,
    )
    pub.create_and_publish(checkout, request, default_branch="main")

    assert seen["owner"] == "acme-inc"
    assert seen["name"] == "thing"
    assert seen["user_login"] == "octocat"
    assert seen["private"] is True
