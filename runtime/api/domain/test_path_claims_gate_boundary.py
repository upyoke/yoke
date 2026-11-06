"""Coverage for the path-claim boundary lifecycle gate.

Wires a real temp git repo, project row, item, and universal lane so the
gate's project-aware path resolution sees an on-disk worktree.
"""

from __future__ import annotations

from runtime.api.domain.path_claims_gate_boundary_test_support import (
    _apply_boundary_schema as _apply_boundary_schema,
    _commit_in_worktree as _commit_in_worktree,
    _git as _git,
    project_repo as project_repo,
    real_db as real_db,
)


from contextlib import closing


from runtime.api.domain._path_claims_test_helpers import (
    local_human,
    seed_target,
)
from yoke_core.domain.path_claims import register
from yoke_core.domain.path_claims_gate_boundary import check_boundary_for_item
from runtime.api.fixtures.file_test_db import connect_test_db


class TestBoundaryGate:
    def test_gate_allows_when_target_not_gated(self, real_db):
        result = check_boundary_for_item(
            item_id=7777,
            target_status="implementing",
            db_path=real_db,
        )
        assert result is None

    def test_gate_allows_when_no_claims_attached(self, real_db):
        result = check_boundary_for_item(
            item_id=7777,
            target_status="reviewed-implementation",
            db_path=real_db,
        )
        assert result is None

    def test_gate_allows_when_committed_change_inside_coverage(
        self, project_repo, real_db
    ):
        # Open the backend DB the gate reads so writes are visible to it.
        with closing(connect_test_db(real_db)) as wconn:
            actor = local_human(wconn)
            target = seed_target(wconn, path_string="src/foo.py")
            register(
                wconn,
                actor_id=actor,
                integration_target="main",
                target_ids=[target],
                item_id=7777,
            )
        _commit_in_worktree(project_repo, name="foo.py")
        result = check_boundary_for_item(
            item_id=7777,
            target_status="reviewed-implementation",
            db_path=real_db,
        )
        assert result is None

    def test_gate_blocks_on_conflict(self, project_repo, real_db):
        with closing(connect_test_db(real_db)) as wconn:
            actor = local_human(wconn)
            target = seed_target(wconn, path_string="src/foo.py")
            seed_target(wconn, path_string="src/bar.py")
            register(
                wconn,
                actor_id=actor,
                integration_target="main",
                target_ids=[target],
                item_id=7777,
            )
        _commit_in_worktree(project_repo, name="foo.py")
        _commit_in_worktree(project_repo, name="bar.py")
        result = check_boundary_for_item(
            item_id=7777,
            target_status="reviewed-implementation",
            db_path=real_db,
        )
        assert result is not None
        assert result["error_code"] == "GATE_PATH_CLAIM_BOUNDARY"
        assert "src/bar.py" in result["error"]

    def test_gate_blocks_on_uncommitted_worktree_drift(self, project_repo, real_db):
        with closing(connect_test_db(real_db)) as wconn:
            actor = local_human(wconn)
            target = seed_target(wconn, path_string="src/foo.py")
            register(
                wconn,
                actor_id=actor,
                integration_target="main",
                target_ids=[target],
                item_id=7777,
            )
        worktree = project_repo / ".worktrees" / "YOK-7777"
        (worktree / "src").mkdir(exist_ok=True)
        (worktree / "src" / "foo.py").write_text("print('dirty')\n")
        result = check_boundary_for_item(
            item_id=7777,
            target_status="reviewed-implementation",
            db_path=real_db,
        )
        assert result is not None
        assert result["error_code"] == "GATE_PATH_CLAIM_BOUNDARY"
        assert "working tree" in result["error"]

    def test_gate_blocks_when_integration_refs_diverged(self, project_repo, real_db):
        base_sha = _git(project_repo, "rev-parse", "main")
        (project_repo / "local.txt").write_text("local\n")
        _git(project_repo, "add", "local.txt")
        _git(project_repo, "commit", "-q", "-m", "local main")
        _git(project_repo, "checkout", "-q", "-b", "origin-side", base_sha)
        (project_repo / "origin.txt").write_text("origin\n")
        _git(project_repo, "add", "origin.txt")
        _git(project_repo, "commit", "-q", "-m", "origin main")
        origin_sha = _git(project_repo, "rev-parse", "HEAD")
        _git(project_repo, "update-ref", "refs/remotes/origin/main", origin_sha)
        _git(project_repo, "checkout", "-q", "main")
        with closing(connect_test_db(real_db)) as wconn:
            actor = local_human(wconn)
            target = seed_target(wconn, path_string="src/foo.py")
            register(
                wconn,
                actor_id=actor,
                integration_target="main",
                target_ids=[target],
                item_id=7777,
            )
        result = check_boundary_for_item(
            item_id=7777,
            target_status="reviewed-implementation",
            db_path=real_db,
        )
        assert result is not None
        assert result["error_code"] == "GATE_PATH_CLAIM_BOUNDARY"
        assert "have diverged" in result["error"]

    def test_gate_is_clear_when_no_claims_and_no_worktree(self, real_db):
        """Nothing declared is genuinely nothing to enforce."""
        with closing(connect_test_db(real_db)) as wconn:
            wconn.execute("DELETE FROM item_worktrees WHERE item_id = 7777")
            wconn.commit()
        result = check_boundary_for_item(
            item_id=7777,
            target_status="reviewed-implementation",
            db_path=real_db,
        )
        assert result is None

    def test_gate_blocks_when_claims_exist_but_no_worktree_does(self, real_db):
        """Coverage with nothing to check it against is not a clean pass."""
        with closing(connect_test_db(real_db)) as wconn:
            actor = local_human(wconn)
            target = seed_target(wconn, path_string="src/foo.py")
            register(
                wconn,
                actor_id=actor,
                integration_target="main",
                target_ids=[target],
                item_id=7777,
            )
            wconn.execute("DELETE FROM item_worktrees WHERE item_id = 7777")
            wconn.commit()
        result = check_boundary_for_item(
            item_id=7777,
            target_status="reviewed-implementation",
            db_path=real_db,
        )
        assert result is not None
        assert result["error_code"] == "GATE_PATH_CLAIM_BOUNDARY"
        assert "no current boundary proof" in result["error"]
        assert "claims path boundary-prove" in result["error"]

    def test_gate_blocks_when_no_integration_ref_resolves(self, project_repo, real_db):
        """Neither ladder rung reachable refuses and names both rungs."""
        with closing(connect_test_db(real_db)) as wconn:
            actor = local_human(wconn)
            target = seed_target(wconn, path_string="src/foo.py")
            register(
                wconn,
                actor_id=actor,
                integration_target="main",
                target_ids=[target],
                item_id=7777,
            )
            wconn.commit()
        _git(project_repo, "branch", "-m", "main", "renamed-trunk")
        result = check_boundary_for_item(
            item_id=7777,
            target_status="reviewed-implementation",
            db_path=real_db,
        )
        assert result is not None
        assert result["error_code"] == "GATE_PATH_CLAIM_BOUNDARY"
        assert "remote_integration_ref" in result["error"]
        assert "local_integration_ref" in result["error"]
