"""Boundary diff anchor — dynamic merge-base of integration head and HEAD.

The anchor is the actual DAG fork point of the branch under check, not
the activation-time recorded SHA. This means routine forward and
backward drift on the integration target leaves the diff range
unchanged: ``origin/main`` moving past activation does not pollute the
diff (the LCA is unchanged), and a branch built from local ``main``
already ahead of ``origin/main`` no longer inherits unrelated commits.

The activation commit SHA recorded on ``path_claims.base_commit_sha``
is preserved as an audit artifact but is not consulted by the boundary
diff.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from yoke_core.domain.path_claims_integration_resolver import (
    compute_anchor_sha,
)


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


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


class TestMergeBaseAnchor:
    def test_anchor_is_merge_base_when_main_advances(self, tmp_path):
        """Branch forks from main at SHA F. Main then advances by two
        unrelated commits. The boundary anchor is still F (the fork
        point), so the diff range covers only branch work."""
        repo = _seed_repo(tmp_path)
        fork_sha = _git(repo, "rev-parse", "HEAD")
        # Branch forks here.
        _git(repo, "checkout", "-q", "-b", "feature")
        (repo / "feature.py").write_text("feat\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "branch work")
        branch_head = _git(repo, "rev-parse", "HEAD")
        # Main advances independently (simulates "another PR landed").
        _git(repo, "checkout", "-q", "main")
        (repo / "drift1.txt").write_text("d1\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "drift1")
        (repo / "drift2.txt").write_text("d2\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "drift2")

        anchor = compute_anchor_sha(
            repo_path=str(repo),
            integration_target="main",
            head_sha=branch_head,
        )
        assert anchor == fork_sha, (
            "anchor should be the DAG fork point regardless of how far "
            "main has advanced"
        )

    def test_anchor_ignores_recorded_snapshot(self, tmp_path):
        """``base_commit_sha`` is no longer consulted — even if a stale
        snapshot row exists at an unrelated SHA, the anchor stays
        merge-base. Tests the contract by simply confirming the helper
        does not accept a snapshot parameter at all."""
        repo = _seed_repo(tmp_path)
        head_sha = _git(repo, "rev-parse", "HEAD")
        # The signature has no conn / base_commit_sha parameter;
        # callers supplying them would get a TypeError. This is the
        # structural assertion that the snapshot path is gone.
        anchor = compute_anchor_sha(
            repo_path=str(repo),
            integration_target="main",
            head_sha=head_sha,
        )
        assert anchor == head_sha
        with pytest.raises(TypeError):
            compute_anchor_sha(
                repo_path=str(repo),
                integration_target="main",
                head_sha=head_sha,
                base_commit_sha="deadbeefcafef00d000001230000000000000000",  # not part of the signature
            )

    def test_unresolvable_target_raises(self, tmp_path):
        """Cannot compute an anchor when the integration target ref is
        absent from the worktree — the resolver bubbles a
        BoundaryCheckError up, matching the existing contract."""
        from yoke_core.domain.path_claims_boundary_git import (
            BoundaryCheckError,
        )

        repo = _seed_repo(tmp_path)
        head_sha = _git(repo, "rev-parse", "HEAD")
        with pytest.raises(BoundaryCheckError, match="cannot resolve"):
            compute_anchor_sha(
                repo_path=str(repo),
                integration_target="release/missing",
                head_sha=head_sha,
            )
