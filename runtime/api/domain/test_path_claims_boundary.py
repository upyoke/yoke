"""Coverage for the committed-git boundary check.

Boots a small temp git repo per test so the diff window has real
commits. Speed-conscious: each helper test runs a few small commits in
under 100ms because git operations dominate the test time budget.
"""

from __future__ import annotations

import os
import subprocess

import pytest

from yoke_core.domain._path_claims_test_helpers import (  # noqa: F401
    conn,
    local_human,
    seed_target,
)
from yoke_core.domain.path_claims import register
from yoke_core.domain.path_claims_boundary import (
    BoundaryCheckError,
    BoundaryCheckStatus,
    boundary_check_for_claim,
    boundary_check_for_paths,
)


def _git(repo, *args, env=None):
    full_env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }
    if env:
        full_env.update(env)
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
        env=full_env,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed: {proc.stderr or proc.stdout}"
        )
    return proc.stdout


@pytest.fixture
def repo(tmp_path):
    """Initialize a git repo with a `main` branch and one base commit."""
    _git(tmp_path, "init", "-q", "--initial-branch=main")
    (tmp_path / "README.md").write_text("# repo\n")
    _git(tmp_path, "add", "README.md")
    _git(tmp_path, "commit", "-q", "-m", "initial")
    _git(tmp_path, "checkout", "-q", "-b", "feature")
    return tmp_path


def _seed_item(conn, *, item_id: int = 7001):
    conn.execute(
        "INSERT INTO items (id, title, type, status, priority, "
        "created_at, updated_at, project_id, project_sequence) "
        "VALUES (%s, 'item', 'issue', 'idea', 'medium', "
        "'2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z', 1, %s)",
        (item_id, item_id),
    )
    conn.commit()
    return item_id


class TestBoundaryCheckForClaim:
    def test_valid_when_committed_change_matches_declared(self, conn, repo):
        actor = local_human(conn)
        item_id = _seed_item(conn)
        target = seed_target(conn, path_string="src/foo.py")
        cid = register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[target], item_id=item_id,
        )
        os.makedirs(repo / "src", exist_ok=True)
        (repo / "src" / "foo.py").write_text("print('x')\n")
        _git(repo, "add", "src/foo.py")
        _git(repo, "commit", "-q", "-m", "feat")
        result = boundary_check_for_claim(
            conn, claim_id=cid, repo_path=str(repo)
        )
        assert result.status == BoundaryCheckStatus.VALID
        assert result.touched_paths == ["src/foo.py"]
        assert result.undeclared_paths == []
        assert result.declared_but_untouched_paths == []

    def test_conflict_when_committed_change_outside_coverage(
        self, conn, repo
    ):
        actor = local_human(conn)
        item_id = _seed_item(conn)
        target = seed_target(conn, path_string="src/foo.py")
        # Make sure the touched-but-undeclared file has its own row in
        # the registry so the diagnostic carries an actionable id.
        seed_target(conn, path_string="src/bar.py")
        cid = register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[target], item_id=item_id,
        )
        os.makedirs(repo / "src", exist_ok=True)
        (repo / "src" / "foo.py").write_text("print('x')\n")
        (repo / "src" / "bar.py").write_text("print('y')\n")
        _git(repo, "add", "src/foo.py", "src/bar.py")
        _git(repo, "commit", "-q", "-m", "two files")
        result = boundary_check_for_claim(
            conn, claim_id=cid, repo_path=str(repo)
        )
        assert result.status == BoundaryCheckStatus.CONFLICT
        assert "src/bar.py" in result.undeclared_paths
        assert result.undeclared_target_ids  # Actionable ids surface

    def test_conflict_when_worktree_has_uncommitted_changes(self, conn, repo):
        actor = local_human(conn)
        item_id = _seed_item(conn)
        target = seed_target(conn, path_string="src/foo.py")
        cid = register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[target], item_id=item_id,
        )
        os.makedirs(repo / "src", exist_ok=True)
        (repo / "src" / "foo.py").write_text("print('dirty')\n")
        result = boundary_check_for_claim(
            conn, claim_id=cid, repo_path=str(repo)
        )
        assert result.status == BoundaryCheckStatus.CONFLICT
        assert result.uncommitted_paths == ["src/foo.py"]
        assert "working tree" in result.diagnostics

    def test_drifted_when_no_committed_change_touches_coverage(
        self, conn, repo
    ):
        actor = local_human(conn)
        item_id = _seed_item(conn)
        target = seed_target(conn, path_string="src/foo.py")
        cid = register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[target], item_id=item_id,
        )
        # No commits on the feature branch beyond the base.
        result = boundary_check_for_claim(
            conn, claim_id=cid, repo_path=str(repo)
        )
        assert result.status == BoundaryCheckStatus.DRIFTED
        assert result.touched_paths == []
        assert "src/foo.py" in result.declared_but_untouched_paths

    def test_rename_resolved_when_both_endpoints_declared(
        self, conn, repo
    ):
        actor = local_human(conn)
        item_id = _seed_item(conn)
        old_target = seed_target(conn, path_string="src/old.py")
        new_target = seed_target(conn, path_string="src/new.py")
        os.makedirs(repo / "src", exist_ok=True)
        # Add the old path to the integration target first so the
        # rename diff has an authoritative source path.
        _git(repo, "checkout", "-q", "main")
        (repo / "src" / "old.py").write_text("print('x')\n")
        _git(repo, "add", "src/old.py")
        _git(repo, "commit", "-q", "-m", "land old")
        _git(repo, "checkout", "-q", "feature")
        _git(repo, "merge", "-q", "main", "--no-edit")
        cid = register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[old_target, new_target], item_id=item_id,
        )
        # Rename the file on the feature branch
        os.rename(repo / "src" / "old.py", repo / "src" / "new.py")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "rename old to new")
        result = boundary_check_for_claim(
            conn, claim_id=cid, repo_path=str(repo)
        )
        assert result.status == BoundaryCheckStatus.RENAME_RESOLVED
        assert result.rename_pairs == [("src/old.py", "src/new.py")]

    def test_unresolvable_integration_target_raises(self, conn, repo):
        actor = local_human(conn)
        item_id = _seed_item(conn)
        target = seed_target(conn, path_string="src/foo.py")
        cid = register(
            conn, actor_id=actor, integration_target="release/none",
            target_ids=[target], item_id=item_id,
        )
        with pytest.raises(BoundaryCheckError, match="cannot resolve"):
            boundary_check_for_claim(
                conn, claim_id=cid, repo_path=str(repo)
            )


class TestGitignoreFiltering:
    """AC-28 / AC-47: ignored committed paths are filtered before classify."""

    def _land_ignore_on_main(self, repo):
        _git(repo, "checkout", "-q", "main")
        (repo / ".gitignore").write_text("qa-artifacts/\n")
        _git(repo, "add", ".gitignore")
        _git(repo, "commit", "-q", "-m", "ignore qa-artifacts")
        _git(repo, "checkout", "-q", "feature")
        _git(repo, "merge", "-q", "main", "--no-edit")

    def test_ignored_committed_path_not_reported_as_undeclared(
        self, conn, repo
    ):
        actor = local_human(conn)
        item_id = _seed_item(conn)
        self._land_ignore_on_main(repo)
        target = seed_target(conn, path_string="src/foo.py")
        cid = register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[target], item_id=item_id,
        )
        os.makedirs(repo / "src", exist_ok=True)
        (repo / "src" / "foo.py").write_text("print('x')\n")
        os.makedirs(repo / "qa-artifacts", exist_ok=True)
        (repo / "qa-artifacts" / "shot.png").write_bytes(b"\x89PNG\r\n")
        # Force-add the ignored file to simulate a runner that bypasses ignore
        _git(repo, "add", "src/foo.py")
        _git(repo, "add", "-f", "qa-artifacts/shot.png")
        _git(repo, "commit", "-q", "-m", "feat with screenshot artifact")
        result = boundary_check_for_claim(
            conn, claim_id=cid, repo_path=str(repo)
        )
        assert result.status == BoundaryCheckStatus.VALID, result.diagnostics
        assert "qa-artifacts/shot.png" not in result.touched_paths
        assert "qa-artifacts/shot.png" not in result.undeclared_paths

    def test_non_ignored_undeclared_path_still_conflicts(self, conn, repo):
        actor = local_human(conn)
        item_id = _seed_item(conn)
        self._land_ignore_on_main(repo)
        target = seed_target(conn, path_string="src/foo.py")
        seed_target(conn, path_string="src/bar.py")
        cid = register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[target], item_id=item_id,
        )
        os.makedirs(repo / "src", exist_ok=True)
        (repo / "src" / "foo.py").write_text("print('x')\n")
        (repo / "src" / "bar.py").write_text("print('y')\n")
        _git(repo, "add", "src/foo.py", "src/bar.py")
        _git(repo, "commit", "-q", "-m", "two tracked files")
        result = boundary_check_for_claim(
            conn, claim_id=cid, repo_path=str(repo)
        )
        assert result.status == BoundaryCheckStatus.CONFLICT
        assert "src/bar.py" in result.undeclared_paths


class TestBoundaryCheckForPaths:
    def test_narrow_rejects_dropping_committed_path(self, conn, repo):
        # Commit two files; ask whether dropping one would still
        # cover the committed work.
        os.makedirs(repo / "src", exist_ok=True)
        (repo / "src" / "foo.py").write_text("print('x')\n")
        (repo / "src" / "bar.py").write_text("print('y')\n")
        _git(repo, "add", "src/foo.py", "src/bar.py")
        _git(repo, "commit", "-q", "-m", "two files")
        seed_target(conn, path_string="src/foo.py")
        seed_target(conn, path_string="src/bar.py")
        result = boundary_check_for_paths(
            conn,
            project_id=1,
            candidate_paths=["src/foo.py"],
            integration_target="main",
            repo_path=str(repo),
        )
        assert result.status == BoundaryCheckStatus.CONFLICT
        assert "src/bar.py" in result.undeclared_paths
        assert result.undeclared_target_ids  # AC-9A: ids surface for amend

    def test_narrow_accepts_when_dropped_path_was_untouched(
        self, conn, repo
    ):
        os.makedirs(repo / "src", exist_ok=True)
        (repo / "src" / "foo.py").write_text("print('x')\n")
        _git(repo, "add", "src/foo.py")
        _git(repo, "commit", "-q", "-m", "one file")
        seed_target(conn, path_string="src/foo.py")
        result = boundary_check_for_paths(
            conn,
            project_id=1,
            candidate_paths=["src/foo.py"],
            integration_target="main",
            repo_path=str(repo),
        )
        assert result.status == BoundaryCheckStatus.VALID
        assert result.undeclared_paths == []
