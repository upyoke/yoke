"""3-way clone-outcome routing through ``import_project``'s outcome applier.

Drives the post-clone remote choreography (just-clone / make-it-mine / fork)
against local temp git repos with the GitHub REST create/fork mocked at the
``github_publish`` seam. Asserts the re-home and fork remote shapes and that the
recorded ``github_repo`` follows the repo the user now owns.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from yoke_cli.config import github_publish
from yoke_cli.config import project_clone_support as clone
from yoke_cli.config import project_onboard
from yoke_cli.config import project_onboard_clone
from yoke_cli.config.project_publish_support import PublishRequest


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=root, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
    )
    return result.stdout.strip()


def _seed_bare_source(tmp_path: Path, name: str, *, branch: str = "main") -> Path:
    work = tmp_path / f"{name}-work"
    work.mkdir()
    _git(work, "init", "--initial-branch", branch)
    _git(work, "config", "user.email", "t@example.com")
    _git(work, "config", "user.name", "Test")
    (work / "README.md").write_text("# source\n", encoding="utf-8")
    _git(work, "add", "README.md")
    _git(work, "commit", "-m", "seed")
    bare = tmp_path / f"{name}.git"
    _git(tmp_path, "clone", "--bare", str(work), str(bare))
    return bare


def _clone_into(tmp_path: Path, bare: Path, name: str) -> Path:
    parent = tmp_path / "checkouts"
    parent.mkdir(exist_ok=True)
    _git(parent, "clone", str(bare), name)
    target = parent / name
    _git(target, "config", "user.email", "t@example.com")
    _git(target, "config", "user.name", "Test")
    return target


@pytest.fixture(autouse=True)
def _local_git_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        clone,
        "run_git",
        lambda root, *args, **_kwargs: _git(root, *args),
    )


def test_just_clone_leaves_origin_on_source(tmp_path: Path) -> None:
    source = _seed_bare_source(tmp_path, "source")
    target = _clone_into(tmp_path, source, "widgets")

    outcome = project_onboard._apply_clone_outcome(
        target, remote_url=str(source), default_branch="main",
        plan=clone.ClonePlan(outcome=clone.CLONE_OUTCOME_JUST_CLONE),
    )

    assert outcome.github_repo is None
    # just-clone records the clone's live checked-out branch.
    assert outcome.branch == "main"
    # Fresh run: every resume flag is False.
    assert (outcome.clone_reused, outcome.repo_reused, outcome.origin_rehomed) == (
        False, False, False,
    )
    assert _git(target, "remote", "get-url", "origin") == str(source)
    assert "upstream" not in _git(target, "remote").split()


def test_just_clone_records_master_source_branch_not_main(tmp_path: Path) -> None:
    # A `master`-default source clones out `master`; the recorded default branch
    # must follow the clone's real branch, never a hardcoded `main` hint.
    source = _seed_bare_source(tmp_path, "source", branch="master")
    target = _clone_into(tmp_path, source, "widgets")
    assert _git(target, "rev-parse", "--abbrev-ref", "HEAD") == "master"

    outcome = project_onboard._apply_clone_outcome(
        target, remote_url=str(source), default_branch="main",
        plan=clone.ClonePlan(outcome=clone.CLONE_OUTCOME_JUST_CLONE),
    )

    assert outcome.github_repo is None
    assert outcome.branch == "master"


def test_make_it_mine_rehomes_keeping_upstream(tmp_path: Path, monkeypatch) -> None:
    source = _seed_bare_source(tmp_path, "source")
    new_origin = tmp_path / "mine.git"
    _git(tmp_path, "init", "--bare", str(new_origin))
    target = _clone_into(tmp_path, source, "widgets")

    monkeypatch.setattr(
        github_publish, "create_repo",
        lambda *a, **k: {"full_name": "octocat/widgets", "private": True},
    )
    # The new origin is built as a clean HTTPS URL by the production code; the
    # https_remote builder is redirected to the local bare repo so the real push
    # lands locally (no network, no SSH host-key prompt).
    monkeypatch.setattr(project_onboard_clone, "https_remote", lambda repo, **_: str(new_origin))

    token = "ghs_make_it_mine_token"
    plan = clone.ClonePlan(
        outcome=clone.CLONE_OUTCOME_MAKE_IT_MINE,
        keep_upstream=True,
        publish=PublishRequest(
            owner="octocat", name="widgets", user_login="octocat", token=token,
        ),
    )
    outcome = project_onboard._apply_clone_outcome(
        target, remote_url=str(source), default_branch="main", plan=plan,
    )

    assert outcome.github_repo == "octocat/widgets"
    # The re-home reports the branch it actually pushed.
    assert outcome.branch == "main"
    # Fresh make-it-mine: the repo was created and origin re-homed this run.
    assert outcome.repo_reused is False
    assert outcome.origin_rehomed is False
    assert _git(target, "remote", "get-url", "origin") == str(new_origin)
    assert _git(target, "remote", "get-url", "upstream") == str(source)
    assert "main" in _git(new_origin, "branch", "--list")
    # SECURITY: the push carried the token only as a request-scoped header — it
    # must never persist in the cloned repo's config or the stored origin URL.
    config_text = (target / ".git" / "config").read_text(encoding="utf-8")
    assert token not in config_text
    assert "extraheader" not in config_text


def test_make_it_mine_clean_copy_drops_upstream(tmp_path: Path, monkeypatch) -> None:
    source = _seed_bare_source(tmp_path, "source")
    new_origin = tmp_path / "mine.git"
    _git(tmp_path, "init", "--bare", str(new_origin))
    target = _clone_into(tmp_path, source, "widgets")

    monkeypatch.setattr(
        github_publish, "create_repo",
        lambda *a, **k: {"full_name": "octocat/widgets", "private": True},
    )
    monkeypatch.setattr(project_onboard_clone, "https_remote", lambda repo, **_: str(new_origin))

    plan = clone.ClonePlan(
        outcome=clone.CLONE_OUTCOME_MAKE_IT_MINE,
        keep_upstream=False,
        publish=PublishRequest(
            owner="octocat", name="widgets", user_login="octocat", token="ghs_x",
            administration_allowed=True,
        ),
    )
    outcome = project_onboard._apply_clone_outcome(
        target, remote_url=str(source), default_branch="main", plan=plan,
    )

    assert outcome.github_repo == "octocat/widgets"
    assert outcome.branch == "main"
    assert _git(target, "remote", "get-url", "origin") == str(new_origin)
    assert "upstream" not in _git(target, "remote").split()


def test_manual_enterprise_repository_attachment_never_creates_repository(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _seed_bare_source(tmp_path, "source")
    new_origin = tmp_path / "enterprise-existing.git"
    _git(tmp_path, "init", "--bare", str(new_origin))
    target = _clone_into(tmp_path, source, "widgets")
    verified: list[dict] = []

    def verify_existing(*_args, **kwargs):
        verified.append(dict(kwargs))
        return {
            "full_name": "acme/widgets-copy",
            "private": False,
            "default_branch": "main",
        }

    monkeypatch.setattr(github_publish, "verify_existing_repo", verify_existing)
    monkeypatch.setattr(
        github_publish,
        "create_repo",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("manual attachment must perform zero create requests")
        ),
    )
    monkeypatch.setattr(
        project_onboard_clone,
        "https_remote",
        lambda _repo, **_kwargs: str(new_origin),
    )
    plan = clone.ClonePlan(
        outcome=clone.CLONE_OUTCOME_MAKE_IT_MINE,
        keep_upstream=True,
        publish=PublishRequest(
            owner="acme",
            name="widgets-copy",
            user_login="octocat",
            token="ghu_enterprise",
            api_url="https://ghe.example/api/v3",
            web_url="https://ghe.example",
            private=False,
            use_machine_github=True,
            create_repository=False,
            repository_id=456,
            installation_id=123,
        ),
    )

    outcome = project_onboard._apply_clone_outcome(
        target,
        remote_url=str(source),
        default_branch="main",
        plan=plan,
    )

    assert outcome.github_repo == "acme/widgets-copy"
    assert verified == [{
        "owner": "acme",
        "name": "widgets-copy",
        "expected_head_sha": _git(target, "rev-parse", "main"),
        "private": False,
        "repository_id": 456,
        "web_url": "https://ghe.example",
    }]
    assert _git(target, "remote", "get-url", "origin") == str(new_origin)
    assert _git(target, "remote", "get-url", "upstream") == str(source)


def test_fork_sets_origin_fork_and_upstream_source(tmp_path: Path, monkeypatch) -> None:
    source = _seed_bare_source(tmp_path, "source")
    fork = tmp_path / "fork.git"
    _git(tmp_path, "init", "--bare", str(fork))
    target = _clone_into(tmp_path, source, "widgets")

    seen: dict = {}

    def _fake_fork(api_url, token, *, owner, repo, **_kwargs):
        seen.update(owner=owner, repo=repo)
        return {"full_name": "octocat/widgets", "private": False}

    monkeypatch.setattr(github_publish, "fork_repo", _fake_fork)
    monkeypatch.setattr(project_onboard_clone, "https_remote", lambda repo, **_: str(fork))

    plan = clone.ClonePlan(
        outcome=clone.CLONE_OUTCOME_FORK, fallback_token="ghs_x",
        fork_allowed=True,
    )
    outcome = project_onboard._apply_clone_outcome(
        target, remote_url="git@github.com:acme/widgets.git",
        default_branch="main", plan=plan,
    )

    assert outcome.github_repo == "octocat/widgets"
    # Fork keeps the source/fork branch; the clone checked out `main`.
    assert outcome.branch == "main"
    assert seen == {"owner": "acme", "repo": "widgets"}
    assert _git(target, "remote", "get-url", "origin") == str(fork)
    assert _git(target, "remote", "get-url", "upstream") == str(source)
