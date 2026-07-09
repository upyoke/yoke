"""3-way clone-outcome routing through ``import_project``'s outcome applier.

Drives the post-clone remote choreography (just-clone / make-it-mine / fork)
against local temp git repos with the GitHub REST create/fork mocked at the
``github_publish`` seam. Asserts the re-home and fork remote shapes and that the
recorded ``github_repo`` follows the repo the user now owns.
"""

from __future__ import annotations

import io
import json
import subprocess
import urllib.error
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
    monkeypatch.setattr(project_onboard_clone, "https_remote", lambda repo: str(new_origin))

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
    monkeypatch.setattr(project_onboard_clone, "https_remote", lambda repo: str(new_origin))

    plan = clone.ClonePlan(
        outcome=clone.CLONE_OUTCOME_MAKE_IT_MINE,
        keep_upstream=False,
        publish=PublishRequest(
            owner="octocat", name="widgets", user_login="octocat", token="ghs_x",
        ),
    )
    outcome = project_onboard._apply_clone_outcome(
        target, remote_url=str(source), default_branch="main", plan=plan,
    )

    assert outcome.github_repo == "octocat/widgets"
    assert outcome.branch == "main"
    assert _git(target, "remote", "get-url", "origin") == str(new_origin)
    assert "upstream" not in _git(target, "remote").split()


def test_fork_sets_origin_fork_and_upstream_source(tmp_path: Path, monkeypatch) -> None:
    source = _seed_bare_source(tmp_path, "source")
    fork = tmp_path / "fork.git"
    _git(tmp_path, "init", "--bare", str(fork))
    target = _clone_into(tmp_path, source, "widgets")

    seen: dict = {}

    def _fake_fork(api_url, token, *, owner, repo):
        seen.update(owner=owner, repo=repo)
        return {"full_name": "octocat/widgets", "private": False}

    monkeypatch.setattr(github_publish, "fork_repo", _fake_fork)
    monkeypatch.setattr(project_onboard_clone, "https_remote", lambda repo: str(fork))

    plan = clone.ClonePlan(
        outcome=clone.CLONE_OUTCOME_FORK, fallback_token="ghs_x",
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


class _ResumeUrlopen:
    """Mocks the GitHub REST seam so the real create_repo runs its 422 resume.

    The create POST answers 422 (name already exists); the repo GET answers the
    existing summary; the commits probe answers 409 (empty). The real re-home
    then re-pushes against the local bare new-origin. git itself is a subprocess
    and never touches this mock.
    """

    def __init__(self) -> None:
        self.paths: list[tuple[str, str]] = []

    def __call__(self, request, timeout: float = 0.0):
        url_path = request.full_url.split("?", 1)[0]
        self.paths.append((request.get_method(), url_path))
        if url_path.endswith("/user/repos"):
            raise self._error(request.full_url, 422, "name already exists")
        if url_path.endswith("/octocat/widgets/commits"):
            raise self._error(request.full_url, 409, "Git Repository is empty")
        if url_path.endswith("/repos/octocat/widgets"):
            return self._ok({
                "full_name": "octocat/widgets",
                "private": True,
                "default_branch": "main",
            })
        raise AssertionError(f"unexpected GitHub call: {request.full_url}")

    @staticmethod
    def _ok(payload: dict):
        class _Resp(io.BytesIO):
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *exc):
                return False

        return _Resp(json.dumps(payload).encode("utf-8"))

    @staticmethod
    def _error(url: str, status: int, message: str) -> urllib.error.HTTPError:
        body = io.BytesIO(json.dumps({"message": message}).encode("utf-8"))
        return urllib.error.HTTPError(url, status, message, {}, body)


def test_make_it_mine_resume_reuses_created_repo_and_repushes(
    tmp_path: Path, monkeypatch,
) -> None:
    # End-to-end resume: the repo was created by a prior run (push hadn't
    # landed), so this run's create POST 422s. The real create_repo reuses the
    # empty repo and the idempotent re-home re-pushes — onboarding completes
    # instead of aborting on "name already exists".
    source = _seed_bare_source(tmp_path, "source")
    new_origin = tmp_path / "mine.git"
    _git(tmp_path, "init", "--bare", str(new_origin))
    target = _clone_into(tmp_path, source, "widgets")

    fake = _ResumeUrlopen()
    monkeypatch.setattr(github_publish.urllib.request, "urlopen", fake)
    monkeypatch.setattr(project_onboard_clone, "https_remote", lambda repo: str(new_origin))

    plan = clone.ClonePlan(
        outcome=clone.CLONE_OUTCOME_MAKE_IT_MINE,
        keep_upstream=False,
        publish=PublishRequest(
            owner="octocat", name="widgets", user_login="octocat", token="ghs_x",
        ),
    )
    outcome = project_onboard._apply_clone_outcome(
        target, remote_url=str(source), default_branch="main", plan=plan,
    )

    assert outcome.github_repo == "octocat/widgets"
    assert outcome.branch == "main"
    # The repo was adopted on the 422 resume path, so repo_reused is surfaced.
    assert outcome.repo_reused is True
    # The reuse probe ran: create POST -> GET repo -> GET commits.
    assert fake.paths[0][0] == "POST"
    assert fake.paths[0][1].endswith("/user/repos")
    assert any(p[1].endswith("/repos/octocat/widgets") for p in fake.paths)
    assert any(p[1].endswith("/octocat/widgets/commits") for p in fake.paths)
    # The idempotent re-home re-pushed: origin points at the reused repo and the
    # branch actually landed on it.
    assert _git(target, "remote", "get-url", "origin") == str(new_origin)
    assert "main" in _git(new_origin, "branch", "--list")
