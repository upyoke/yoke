"""Upstream freshness never loses local work and never starts work stale.

Every case here builds a real external project — a bare remote plus a
clone, with a default branch that is deliberately not ``main`` in the case
that proves the branch name is read rather than assumed — so the git
behaviour being relied on is the git behaviour under test.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from yoke_core.domain import repo_upstream_freshness as freshness
from yoke_core.domain.repo_upstream_freshness import refresh_base_branch


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


def _commit(repo: Path, name: str, body: str) -> str:
    (repo / name).write_text(body)
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", f"add {name}")
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture(autouse=True)
def _clear_cache():
    freshness.reset_cache()
    yield
    freshness.reset_cache()


@pytest.fixture
def project(tmp_path: Path) -> tuple[Path, Path, str]:
    """An external project: bare remote, clone, non-``main`` default branch."""
    default = "trunk"
    origin = tmp_path / "origin.git"
    seed = tmp_path / "seed"
    subprocess.run(
        ["git", "init", "-q", "--bare", f"--initial-branch={default}", str(origin)],
        check=True,
    )
    subprocess.run(["git", "init", "-q", f"--initial-branch={default}", str(seed)], check=True)
    _git(seed, "config", "user.email", "test@example.com")
    _git(seed, "config", "user.name", "Test")
    _commit(seed, "README.md", "seed\n")
    _git(seed, "remote", "add", "origin", str(origin))
    _git(seed, "push", "-q", "-u", "origin", default)

    checkout = tmp_path / "checkout"
    subprocess.run(
        ["git", "clone", "-q", str(origin), str(checkout)], check=True
    )
    _git(checkout, "config", "user.email", "test@example.com")
    _git(checkout, "config", "user.name", "Test")
    return checkout, seed, default


def _advance_remote(seed: Path, default: str, name: str = "upstream.txt") -> str:
    sha = _commit(seed, name, "from the remote\n")
    _git(seed, "push", "-q", "origin", default)
    return sha


def test_remote_ahead_fast_forwards_and_names_the_lane_base(project):
    checkout, seed, default = project
    remote_sha = _advance_remote(seed, default)

    result = refresh_base_branch(str(checkout), default)

    assert result.state == freshness.STATE_FAST_FORWARDED
    assert result.behind == 1 and result.ahead == 0
    assert result.lane_base_ref == remote_sha
    assert _git(checkout, "rev-parse", default) == remote_sha
    assert not result.needs_attention and not result.blocked


def test_already_current_says_nothing(project):
    checkout, _seed, default = project

    result = refresh_base_branch(str(checkout), default)

    assert result.state == freshness.STATE_CURRENT
    assert result.note == ""
    assert result.lane_base_ref == result.local_sha


def test_local_ahead_keeps_its_commits_and_stays_the_lane_base(project):
    checkout, _seed, default = project
    local_sha = _commit(checkout, "local.txt", "mine\n")

    result = refresh_base_branch(str(checkout), default)

    assert result.state == freshness.STATE_LOCAL_AHEAD
    assert result.ahead == 1 and result.behind == 0
    assert result.lane_base_ref == default
    assert result.needs_attention and not result.blocked
    assert _git(checkout, "rev-parse", default) == local_sha


def test_diverged_is_reported_and_never_replayed(project):
    checkout, seed, default = project
    _advance_remote(seed, default)
    local_sha = _commit(checkout, "local.txt", "mine\n")

    result = refresh_base_branch(str(checkout), default)

    assert result.state == freshness.STATE_DIVERGED
    assert result.ahead == 1 and result.behind == 1
    assert result.lane_base_ref == default
    assert "rebase" in result.note
    assert _git(checkout, "rev-parse", default) == local_sha
    assert not result.blocked


def test_uncommitted_change_in_the_way_refuses_with_its_recovery(project):
    checkout, seed, default = project
    _advance_remote(seed, default, name="README.md")
    (checkout / "README.md").write_text("edited but never committed\n")

    result = refresh_base_branch(str(checkout), default)

    assert result.state == freshness.STATE_BEHIND_NOT_UPDATED
    assert result.blocked and result.needs_attention
    assert "commit or stash" in result.note
    # The local branch did not move and the edit is still there.
    assert _git(checkout, "rev-parse", default) == result.local_sha
    assert (checkout / "README.md").read_text() == "edited but never committed\n"
    # A lane started now still gets the current upstream revision.
    assert result.lane_base_ref == result.upstream_sha


def test_unrelated_uncommitted_change_survives_the_fast_forward(project):
    checkout, seed, default = project
    remote_sha = _advance_remote(seed, default)
    (checkout / "scratch.txt").write_text("work in progress\n")

    result = refresh_base_branch(str(checkout), default)

    assert result.state == freshness.STATE_FAST_FORWARDED
    assert _git(checkout, "rev-parse", default) == remote_sha
    assert (checkout / "scratch.txt").read_text() == "work in progress\n"


def test_branch_checked_out_elsewhere_is_left_alone(project, tmp_path):
    checkout, seed, default = project
    _advance_remote(seed, default)
    _git(checkout, "checkout", "-q", "-b", "lane")
    borrowed = tmp_path / "borrowed"
    _git(checkout, "worktree", "add", "-q", str(borrowed), default)

    result = refresh_base_branch(str(checkout), default)

    assert result.state == freshness.STATE_BEHIND_NOT_UPDATED
    assert str(borrowed) in result.note
    assert result.lane_base_ref == result.upstream_sha


def test_fetch_failure_reports_and_leaves_work_on_the_local_branch(project):
    checkout, _seed, default = project
    _git(checkout, "remote", "set-url", "origin", str(checkout / "gone.git"))

    result = refresh_base_branch(str(checkout), default)

    assert result.state == freshness.STATE_FETCH_FAILED
    assert result.needs_attention and not result.blocked
    assert result.lane_base_ref == default
    assert "Recovery" in result.note


def test_project_without_a_remote_is_silent(tmp_path):
    repo = tmp_path / "local-only"
    subprocess.run(["git", "init", "-q", "--initial-branch=main", str(repo)], check=True)
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _commit(repo, "README.md", "local\n")

    result = refresh_base_branch(str(repo), "main")

    assert result.state == freshness.STATE_NO_REMOTE
    assert result.note == ""
    assert result.lane_base_ref == "main"


def test_several_remotes_and_no_tracking_record_refuses_to_guess(project):
    checkout, _seed, default = project
    _git(checkout, "remote", "add", "mirror", str(checkout))
    _git(checkout, "config", "--unset", f"branch.{default}.remote")

    result = refresh_base_branch(str(checkout), default)

    assert result.state == freshness.STATE_REMOTE_UNRESOLVED
    assert "--set-upstream-to" in result.note


def test_default_branch_is_read_from_the_remote_when_unnamed(project):
    checkout, seed, default = project
    remote_sha = _advance_remote(seed, default)

    result = refresh_base_branch(str(checkout))

    assert result.base_branch == default
    assert result.state == freshness.STATE_FAST_FORWARDED
    assert result.lane_base_ref == remote_sha


def test_one_fetch_per_checkout_per_process(project, monkeypatch):
    checkout, seed, default = project
    _advance_remote(seed, default)
    fetches: list[str] = []
    real_fetch = freshness.upstream_git.fetch_branch

    def counted(repo_root, remote, base_branch):
        fetches.append(base_branch)
        return real_fetch(repo_root, remote, base_branch)

    monkeypatch.setattr(freshness.upstream_git, "fetch_branch", counted)

    first = refresh_base_branch(str(checkout), default)
    second = refresh_base_branch(str(checkout), default)

    assert fetches == [default]
    assert second is first
    assert refresh_base_branch(str(checkout), default, use_cache=False) is not first
    assert len(fetches) == 2


def test_missing_checkout_root_is_unreadable_not_a_crash():
    result = refresh_base_branch("")

    assert result.state == freshness.STATE_UNREADABLE
    assert result.needs_attention
