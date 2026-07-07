"""Tests for the deliberate integration-target resolver.

Covers:

* origin-then-local resolution (the canonical rule)
* fallback to local when origin is missing
* divergence detection raises before activate or boundary tries anything
* anchor SHA computation: dynamic merge-base of integration head and
  worktree HEAD; the activation snapshot is no longer consulted.

Internal git ops shell out to a real ``git`` repo inside ``tmp_path``
so the resolver's branching logic is exercised end-to-end.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from yoke_core.domain.path_claims_integration_resolver import (
    IntegrationTargetDiverged,
    compute_anchor_sha,
    resolve_integration_head_with_divergence_check,
)

def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


class _UnusedConnection:
    """Connection-shaped compatibility arg; resolver no longer reads it."""

    def close(self) -> None:
        pass


def _make_conn():
    return _UnusedConnection()


def _seed_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("hi\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "first")
    return repo


def _seed_origin_clone(repo: Path, tmp_path: Path) -> Path:
    """Clone ``repo`` into a sibling, then add origin pointing back."""
    clone = tmp_path / "clone"
    _git(repo, "clone", "-q", "--no-local", str(repo), str(clone))
    return clone


class TestResolveOriginThenLocal:
    def test_origin_wins_when_both_exist(self, tmp_path):
        repo = _seed_repo(tmp_path)
        # Add a remote tracking ref by faking it.
        # Simpler: clone and verify origin/main resolves.
        clone = _seed_origin_clone(repo, tmp_path)
        conn = _make_conn()
        try:
            sha = resolve_integration_head_with_divergence_check(
                conn,
                project_id="demo",
                repo_path=str(clone),
                integration_target="main",
            )
            origin_sha = _git(clone, "rev-parse", "refs/remotes/origin/main")
            assert sha == origin_sha
        finally:
            conn.close()

    def test_local_when_origin_missing(self, tmp_path):
        repo = _seed_repo(tmp_path)
        conn = _make_conn()
        try:
            sha = resolve_integration_head_with_divergence_check(
                conn,
                project_id="demo",
                repo_path=str(repo),
                integration_target="main",
            )
            local_sha = _git(repo, "rev-parse", "refs/heads/main")
            assert sha == local_sha
        finally:
            conn.close()


class TestDivergence:
    def test_diverged_raises(self, tmp_path):
        repo = _seed_repo(tmp_path)
        clone = _seed_origin_clone(repo, tmp_path)
        # Add a commit to clone (local-only).
        (clone / "local.txt").write_text("local\n")
        _git(clone, "add", "-A")
        _git(clone, "commit", "-q", "-m", "local-only")
        # And to upstream (origin-only).
        (repo / "origin.txt").write_text("origin\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "origin-only")
        # Refresh remote tracking from the clone side.
        _git(clone, "fetch", "-q", "origin")
        # Now origin/main and refs/heads/main should be divergent.
        conn = _make_conn()
        try:
            with pytest.raises(IntegrationTargetDiverged):
                resolve_integration_head_with_divergence_check(
                    conn,
                    project_id="demo",
                    repo_path=str(clone),
                    integration_target="main",
                )
        finally:
            conn.close()

    def test_local_ahead_is_not_divergence(self, tmp_path):
        """When local has commits not yet pushed, that is normal — origin
        is the canonical SHA. No divergence error."""
        repo = _seed_repo(tmp_path)
        clone = _seed_origin_clone(repo, tmp_path)
        (clone / "local.txt").write_text("local\n")
        _git(clone, "add", "-A")
        _git(clone, "commit", "-q", "-m", "local-only")
        # No origin-only commits — local is ahead.
        conn = _make_conn()
        try:
            sha = resolve_integration_head_with_divergence_check(
                conn,
                project_id="demo",
                repo_path=str(clone),
                integration_target="main",
            )
            origin_sha = _git(clone, "rev-parse", "refs/remotes/origin/main")
            assert sha == origin_sha
        finally:
            conn.close()


class TestAnchorSha:
    def test_returns_merge_base_with_main(self, tmp_path):
        """Single-branch repo: merge-base of main and HEAD is HEAD."""
        repo = _seed_repo(tmp_path)
        head = _git(repo, "rev-parse", "HEAD")
        anchor = compute_anchor_sha(
            repo_path=str(repo),
            integration_target="main",
            head_sha=head,
        )
        assert anchor == head

    def test_anchor_is_fork_point_after_main_advances(self, tmp_path):
        """Branch forks at SHA F, main advances after fork — the anchor
        stays at F (the actual DAG fork point)."""
        repo = _seed_repo(tmp_path)
        fork = _git(repo, "rev-parse", "HEAD")
        _git(repo, "checkout", "-q", "-b", "feature")
        (repo / "feat.py").write_text("feat\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "branch work")
        branch_head = _git(repo, "rev-parse", "HEAD")
        _git(repo, "checkout", "-q", "main")
        (repo / "drift.txt").write_text("d\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "drift")
        anchor = compute_anchor_sha(
            repo_path=str(repo),
            integration_target="main",
            head_sha=branch_head,
        )
        assert anchor == fork
