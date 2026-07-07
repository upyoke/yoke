"""Regression scenarios for the merge-base boundary anchor.

Covers the core merge-base boundary scenarios:

* AC-2: branch built from local main while local was ahead of origin —
  no false positive on the unpushed origin-vs-local commits.
* AC-3: origin moves forward after activation — branch unchanged, the
  boundary still passes (the LCA is invariant under origin moving).
* AC-4: branch genuinely commits a file outside its declared coverage —
  the gate still blocks with the canonical "K committed file(s)
  outside declared coverage; offending paths: ..." diagnostic.
* AC-5: origin and local main have actually diverged — the divergence
  detector fires before the boundary check tries anything.

Each scenario boots a real tmp git repo so the merge-base + diff path
is exercised end-to-end. No mocks of git output.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from yoke_core.domain._path_claims_test_helpers import (  # noqa: F401
    conn,
    local_human,
    seed_target,
)
from yoke_core.domain.path_claims import register
from yoke_core.domain.path_claims_boundary import (
    BoundaryCheckStatus,
    boundary_check_for_claim,
)
from yoke_core.domain.path_claims_integration_resolver import (
    IntegrationTargetDiverged,
    resolve_integration_head_with_divergence_check,
)


def _git(repo: Path, *args: str) -> str:
    full_env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }
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
    return proc.stdout.strip()


def _seed_origin_clone(tmp_path: Path) -> tuple[Path, Path]:
    """Create an ``origin`` repo plus a ``clone`` with origin tracking.

    Returns ``(origin, clone)``. The clone has ``main`` checked out and
    ``origin/main`` pointing at the same commit as origin's main tip.
    """
    origin = tmp_path / "origin"
    origin.mkdir()
    _git(origin, "init", "-q", "--initial-branch=main")
    (origin / "README.md").write_text("hi\n")
    _git(origin, "add", "-A")
    _git(origin, "commit", "-q", "-m", "first")
    clone = tmp_path / "clone"
    _git(origin, "clone", "-q", "--no-local", str(origin), str(clone))
    return origin, clone


def _seed_item(conn, *, item_id: int = 9001):
    conn.execute(
        "INSERT INTO items (id, title, type, status, priority, "
        "created_at, updated_at, project_id, project_sequence) "
        "VALUES (%s, 'item', 'issue', 'idea', 'medium', "
        "'2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z', 1, %s)",
        (item_id, item_id),
    )
    conn.commit()
    return item_id


class TestMergeBaseBoundaryRegression:
    def test_local_ahead_of_origin_at_fork_no_false_positive(
        self, conn, tmp_path,
    ):
        """AC-2: local main is one commit ahead of origin/main when the
        branch is created. The branch only touches its declared file.
        Boundary gate must accept — the commits between origin and
        local were already on main at fork time and are not branch
        work."""
        _origin, clone = _seed_origin_clone(tmp_path)
        # Local main advances by one commit (touches an unrelated path);
        # this commit is NOT pushed to origin.
        (clone / "unrelated.md").write_text("local-only\n")
        _git(clone, "add", "-A")
        _git(clone, "commit", "-q", "-m", "local-only commit on main")
        # Branch off local main and touch only the declared file.
        _git(clone, "checkout", "-q", "-b", "feature")
        os.makedirs(clone / "src", exist_ok=True)
        (clone / "src" / "foo.py").write_text("print('x')\n")
        _git(clone, "add", "-A")
        _git(clone, "commit", "-q", "-m", "feat")

        actor = local_human(conn)
        item_id = _seed_item(conn)
        target = seed_target(conn, path_string="src/foo.py")
        cid = register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[target], item_id=item_id,
        )
        result = boundary_check_for_claim(
            conn, claim_id=cid, repo_path=str(clone),
        )
        assert result.status == BoundaryCheckStatus.VALID
        assert result.touched_paths == ["src/foo.py"]
        assert result.undeclared_paths == []

    def test_origin_advances_after_activation_no_false_positive(
        self, conn, tmp_path,
    ):
        """AC-3: a branch is created from main, then origin/main moves
        forward (an unrelated PR landed). The branch keeps only its
        declared file. Boundary gate must still accept — the merge-base
        is invariant under the integration target moving forward."""
        origin, clone = _seed_origin_clone(tmp_path)
        # Branch off the clone; touch only the declared file.
        _git(clone, "checkout", "-q", "-b", "feature")
        os.makedirs(clone / "src", exist_ok=True)
        (clone / "src" / "foo.py").write_text("print('x')\n")
        _git(clone, "add", "-A")
        _git(clone, "commit", "-q", "-m", "feat")
        # Now origin advances.
        (origin / "other.md").write_text("origin-pr\n")
        _git(origin, "add", "-A")
        _git(origin, "commit", "-q", "-m", "another PR landed")
        _git(clone, "fetch", "-q", "origin")

        actor = local_human(conn)
        item_id = _seed_item(conn)
        target = seed_target(conn, path_string="src/foo.py")
        cid = register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[target], item_id=item_id,
        )
        result = boundary_check_for_claim(
            conn, claim_id=cid, repo_path=str(clone),
        )
        assert result.status == BoundaryCheckStatus.VALID
        assert result.touched_paths == ["src/foo.py"]
        assert result.undeclared_paths == []

    def test_genuine_out_of_coverage_commit_still_blocks(
        self, conn, tmp_path,
    ):
        """AC-4: branch commits both the declared file AND an
        undeclared file. The gate must still flag the undeclared path
        with the canonical diagnostic."""
        _origin, clone = _seed_origin_clone(tmp_path)
        _git(clone, "checkout", "-q", "-b", "feature")
        os.makedirs(clone / "src", exist_ok=True)
        (clone / "src" / "foo.py").write_text("print('x')\n")
        (clone / "src" / "bar.py").write_text("print('y')\n")
        _git(clone, "add", "-A")
        _git(clone, "commit", "-q", "-m", "two files")

        actor = local_human(conn)
        item_id = _seed_item(conn)
        target = seed_target(conn, path_string="src/foo.py")
        seed_target(conn, path_string="src/bar.py")
        cid = register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[target], item_id=item_id,
        )
        result = boundary_check_for_claim(
            conn, claim_id=cid, repo_path=str(clone),
        )
        assert result.status == BoundaryCheckStatus.CONFLICT
        assert "src/bar.py" in result.undeclared_paths
        assert "outside declared coverage" in result.diagnostics

    def test_diverged_refs_still_raise(self, conn, tmp_path):
        """AC-5: origin and local main have actually diverged (each has
        a unique commit the other lacks). The divergence detector must
        fire before any boundary work."""
        origin, clone = _seed_origin_clone(tmp_path)
        # Local-only commit.
        (clone / "local.txt").write_text("local\n")
        _git(clone, "add", "-A")
        _git(clone, "commit", "-q", "-m", "local-only")
        # Origin-only commit.
        (origin / "origin.txt").write_text("origin\n")
        _git(origin, "add", "-A")
        _git(origin, "commit", "-q", "-m", "origin-only")
        _git(clone, "fetch", "-q", "origin")
        # The activation phase is where divergence is enforced first;
        # asserting on its resolver entry point keeps the regression
        # focused on the boundary contract's prerequisite.
        with pytest.raises(IntegrationTargetDiverged):
            resolve_integration_head_with_divergence_check(
                conn,
                project_id="yoke",
                repo_path=str(clone),
                integration_target="main",
            )
        actor = local_human(conn)
        item_id = _seed_item(conn)
        target = seed_target(conn, path_string="src/foo.py")
        cid = register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[target], item_id=item_id,
        )
        with pytest.raises(IntegrationTargetDiverged):
            boundary_check_for_claim(
                conn, claim_id=cid, repo_path=str(clone),
            )
