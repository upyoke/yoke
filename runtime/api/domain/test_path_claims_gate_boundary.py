"""Coverage for the path-claim boundary lifecycle gate.

Wires a real temp git repo, project row, item, and universal lane so the
gate's project-aware path resolution sees an on-disk worktree.
"""

from __future__ import annotations

import os
import subprocess
from contextlib import closing

import pytest

from runtime.api.domain._path_claims_test_helpers import (
    local_human,
    seed_target,
)
from yoke_core.domain.path_claims import register
from yoke_core.domain.gate_satisfier_stamp import read_rungs
from yoke_core.domain.path_claims_gate_boundary import check_boundary_for_item
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from runtime.api.fixtures.machine_config_test import register_machine_checkout


def _git(repo, *args):
    full_env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "test@x",
        "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "test@x",
    }
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True, capture_output=True, text=True, env=full_env,
    )
    return proc.stdout.strip()


@pytest.fixture
def project_repo(tmp_path):
    """Project repo with a worktree under .worktrees/ for the test item."""
    repo = tmp_path / "project"
    repo.mkdir()
    _git(repo, "init", "-q", "--initial-branch=main")
    (repo / "README.md").write_text("# repo\n")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "initial")
    # Provision the canonical worktree path the gate will discover
    worktree_dir = repo / ".worktrees" / "YOK-7777"
    _git(repo, "worktree", "add", "-q", "-b", "YOK-7777", str(worktree_dir))
    return repo


def _apply_boundary_schema(project_repo):
    """Return an ``init_test_db`` strategy seeding the boundary substrate.

    Builds the same minimal schema the ``conn`` fixture provides (core +
    events + path registry + actor/path-claim tables + canonical actors)
    plus the ``projects`` table the gate's project-aware lookup needs,
    then seeds the project row (pointing at ``project_repo``), item, and
    universal lane. Resolves its connection through the backend
    factory so the gate, which re-opens the DB via ``db_helpers.connect``
    (the same factory), reads the data the test writes on either engine —
    the VACUUM-INTO-a-SQLite-file path the legacy fixture used was
    invisible to a Postgres-backed gate.
    """

    def _apply() -> None:
        from yoke_core.domain import db_backend
        from yoke_core.domain.actors import seed_canonical_actors
        from yoke_core.domain.events_schema import _create_events_table
        from yoke_core.domain.gate_satisfaction_schema import (
            create_gate_satisfaction_tables,
        )
        from yoke_core.domain.schema_init_actor_path_claim_tables import (
            create_actor_path_claim_tables,
        )
        from yoke_core.domain.schema_init_path_tables import (
            create_path_registry_tables,
        )
        from yoke_core.domain.schema_init_tables import create_core_tables
        from yoke_core.domain.workflow_registry import (
            converge_builtin_workflows,
        )

        c = db_backend.connect()
        try:
            create_core_tables(c)
            converge_builtin_workflows(c)
            _create_events_table(c)
            create_path_registry_tables(c)
            create_actor_path_claim_tables(c)
            create_gate_satisfaction_tables(c)
            seed_canonical_actors(c)
            register_machine_checkout(project_repo.parent, project_repo, 1)
            c.execute(
                "INSERT INTO projects "
                "(id, slug, name, default_branch, github_repo, "
                "public_item_prefix, created_at) "
                "VALUES (1, 'yoke', 'Yoke', 'main', 'test/test', "
                "'YOK', '2026-05-01T00:00:00Z') "
                "ON CONFLICT (id) DO UPDATE SET slug = EXCLUDED.slug",
            )
            c.execute(
                "INSERT INTO items (id, title, workflow_id, workflow_version_id, status, priority, "
                "created_at, updated_at, project_id, project_sequence) "
                "VALUES (7777, 'item', 'issue', (SELECT current_version_id FROM workflows WHERE id='issue'), 'implementing', 'medium', "
                "'2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z', 1, 7777)",
            )
            c.execute(
                "INSERT INTO item_worktrees "
                "(item_id, branch, path, lane_role, state, "
                "created_at, updated_at) "
                "VALUES (7777, 'YOK-7777', %s, 'implementation', 'active', "
                "'2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z')",
                (str(project_repo / ".worktrees" / "YOK-7777"),),
            )
            c.commit()
        finally:
            c.close()

    return _apply


@pytest.fixture
def real_db(project_repo, tmp_path):
    """Backend-appropriate DB the gate can re-open via path.

    On SQLite the yielded token is a real file; on Postgres it is a
    disposable per-test database with the schema applied through the
    backend factory and ``YOKE_PG_DSN`` repointed for the context, so
    the factory-routed gate and the test's ``connect_test_db`` writes hit
    the same database.
    """
    with init_test_db(
        tmp_path, apply_schema=_apply_boundary_schema(project_repo)
    ) as db_path:
        yield db_path


def _commit_in_worktree(project_repo, *, name: str):
    worktree = project_repo / ".worktrees" / "YOK-7777"
    src = worktree / "src"
    src.mkdir(exist_ok=True)
    (src / name).write_text("print('x')\n")
    _git(worktree, "add", f"src/{name}")
    _git(worktree, "commit", "-q", "-m", f"add src/{name}")


class TestBoundaryGate:
    def test_gate_allows_when_target_not_gated(self, real_db):
        result = check_boundary_for_item(
            item_id=7777, target_status="implementing", db_path=real_db,
        )
        assert result is None

    def test_gate_allows_when_no_claims_attached(self, real_db):
        result = check_boundary_for_item(
            item_id=7777, target_status="reviewed-implementation",
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
                wconn, actor_id=actor, integration_target="main",
                target_ids=[target], item_id=7777,
            )
        _commit_in_worktree(project_repo, name="foo.py")
        result = check_boundary_for_item(
            item_id=7777, target_status="reviewed-implementation",
            db_path=real_db,
        )
        assert result is None

    def test_gate_blocks_on_conflict(self, project_repo, real_db):
        with closing(connect_test_db(real_db)) as wconn:
            actor = local_human(wconn)
            target = seed_target(wconn, path_string="src/foo.py")
            seed_target(wconn, path_string="src/bar.py")
            register(
                wconn, actor_id=actor, integration_target="main",
                target_ids=[target], item_id=7777,
            )
        _commit_in_worktree(project_repo, name="foo.py")
        _commit_in_worktree(project_repo, name="bar.py")
        result = check_boundary_for_item(
            item_id=7777, target_status="reviewed-implementation",
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
                wconn, actor_id=actor, integration_target="main",
                target_ids=[target], item_id=7777,
            )
        worktree = project_repo / ".worktrees" / "YOK-7777"
        (worktree / "src").mkdir(exist_ok=True)
        (worktree / "src" / "foo.py").write_text("print('dirty')\n")
        result = check_boundary_for_item(
            item_id=7777, target_status="reviewed-implementation",
            db_path=real_db,
        )
        assert result is not None
        assert result["error_code"] == "GATE_PATH_CLAIM_BOUNDARY"
        assert "working tree" in result["error"]

    def test_gate_blocks_when_integration_refs_diverged(
        self, project_repo, real_db
    ):
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
                wconn, actor_id=actor, integration_target="main",
                target_ids=[target], item_id=7777,
            )
        result = check_boundary_for_item(
            item_id=7777, target_status="reviewed-implementation",
            db_path=real_db,
        )
        assert result is not None
        assert result["error_code"] == "GATE_PATH_CLAIM_BOUNDARY"
        assert "have diverged" in result["error"]

    def test_gate_is_clear_when_no_claims_and_no_worktree(self, real_db):
        """Nothing declared is genuinely nothing to enforce."""
        with closing(connect_test_db(real_db)) as wconn:
            wconn.execute(
                "DELETE FROM item_worktrees WHERE item_id = 7777"
            )
            wconn.commit()
        result = check_boundary_for_item(
            item_id=7777, target_status="reviewed-implementation",
            db_path=real_db,
        )
        assert result is None

    def test_gate_blocks_when_claims_exist_but_no_worktree_does(self, real_db):
        """Coverage with nothing to check it against is not a clean pass."""
        with closing(connect_test_db(real_db)) as wconn:
            actor = local_human(wconn)
            target = seed_target(wconn, path_string="src/foo.py")
            register(
                wconn, actor_id=actor, integration_target="main",
                target_ids=[target], item_id=7777,
            )
            wconn.execute("DELETE FROM item_worktrees WHERE item_id = 7777")
            wconn.commit()
        result = check_boundary_for_item(
            item_id=7777, target_status="reviewed-implementation",
            db_path=real_db,
        )
        assert result is not None
        assert result["error_code"] == "GATE_PATH_CLAIM_BOUNDARY"
        assert "no resolvable worktree" in result["error"]
        assert "worktree prepare" in result["error"]

    def test_gate_blocks_when_no_integration_ref_resolves(
        self, project_repo, real_db
    ):
        """Neither ladder rung reachable refuses and names both rungs."""
        with closing(connect_test_db(real_db)) as wconn:
            actor = local_human(wconn)
            target = seed_target(wconn, path_string="src/foo.py")
            register(
                wconn, actor_id=actor, integration_target="main",
                target_ids=[target], item_id=7777,
            )
            wconn.commit()
        _git(project_repo, "branch", "-m", "main", "renamed-trunk")
        result = check_boundary_for_item(
            item_id=7777, target_status="reviewed-implementation",
            db_path=real_db,
        )
        assert result is not None
        assert result["error_code"] == "GATE_PATH_CLAIM_BOUNDARY"
        assert "remote_integration_ref" in result["error"]
        assert "local_integration_ref" in result["error"]

    def test_clear_boundary_stamps_the_rung_it_resolved(
        self, project_repo, real_db
    ):
        """The item records which integration ref proved the boundary."""
        with closing(connect_test_db(real_db)) as wconn:
            actor = local_human(wconn)
            target = seed_target(wconn, path_string="src/foo.py")
            register(
                wconn, actor_id=actor, integration_target="main",
                target_ids=[target], item_id=7777,
            )
        _commit_in_worktree(project_repo, name="foo.py")
        assert check_boundary_for_item(
            item_id=7777, target_status="reviewed-implementation",
            db_path=real_db,
        ) is None
        with closing(connect_test_db(real_db)) as rconn:
            stamps = read_rungs(rconn, 7777)
        assert [s["obligation"] for s in stamps] == ["path_claim_boundary"]
        assert stamps[0]["rung_id"] == "local_integration_ref"
        assert stamps[0]["target_status"] == "reviewed-implementation"

    def test_remote_ref_outranks_the_local_one_in_the_stamp(
        self, project_repo, real_db
    ):
        """A project with a remote proves against what it integrates into."""
        with closing(connect_test_db(real_db)) as wconn:
            actor = local_human(wconn)
            target = seed_target(wconn, path_string="src/foo.py")
            register(
                wconn, actor_id=actor, integration_target="main",
                target_ids=[target], item_id=7777,
            )
        _commit_in_worktree(project_repo, name="foo.py")
        _git(
            project_repo, "update-ref", "refs/remotes/origin/main",
            _git(project_repo, "rev-parse", "main"),
        )
        assert check_boundary_for_item(
            item_id=7777, target_status="reviewed-implementation",
            db_path=real_db,
        ) is None
        with closing(connect_test_db(real_db)) as rconn:
            stamps = read_rungs(rconn, 7777)
        assert stamps[0]["rung_id"] == "remote_integration_ref"
