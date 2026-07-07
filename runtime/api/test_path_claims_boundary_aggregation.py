"""AC-23: per-item aggregation in :func:`check_boundary_for_item`.

Single-claim items keep today's behavior. Multi-claim items accept when
the union of declared coverage across all non-terminal claims covers
every touched path, even if individual claims reported conflict on
their own narrower coverage. Truly out-of-coverage paths still reject.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from runtime.api.fixtures.file_test_db import init_test_db
from runtime.api.fixtures.machine_config_test import register_machine_checkout
from yoke_core.domain import path_claims_gate_boundary as _gate


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


def _make_branch_apply_schema(repo_root: Path):
    """Zero-arg ``apply_schema`` seeding the minimal aggregation-gate tables.

    Builds ``items`` + ``projects`` + ``path_claims`` against the
    backend-resolved DB and seeds item 9 / project ``demo`` / two active
    claims, so the gate (which re-resolves its own backend connection from
    ``db_path``) reads the same rows on SQLite and Postgres.
    """

    def _apply() -> None:
        from yoke_core.domain import db_backend

        conn = db_backend.connect()
        try:
            conn.execute(
                "CREATE TABLE items ("
                "id INTEGER PRIMARY KEY, worktree TEXT, project_id INTEGER)"
            )
            conn.execute(
                "CREATE TABLE projects ("
                "id INTEGER PRIMARY KEY, slug TEXT UNIQUE)"
            )
            conn.execute(
                "CREATE TABLE path_claims ("
                "id INTEGER PRIMARY KEY, item_id INTEGER, state TEXT)"
            )
            conn.execute(
                "INSERT INTO projects (id, slug) VALUES (3, 'demo')",
            )
            register_machine_checkout(repo_root.parent / "machine-config", repo_root, 3)
            conn.execute("INSERT INTO items VALUES (9, 'YOK-9', 3)")
            conn.execute("INSERT INTO path_claims VALUES (1, 9, 'active')")
            conn.execute("INSERT INTO path_claims VALUES (2, 9, 'active')")
            conn.commit()
        finally:
            conn.close()

    return _apply


class TestAggregationBranching:
    def test_two_claims_union_covers_everything(self, tmp_path, monkeypatch):
        """Two claims, neither covers all touched paths individually,
        but the union does — accept (no rejection)."""
        # Stub out the inner boundary_check_for_claim so we control the
        # per-claim verdicts and exercise only the aggregation logic.
        from yoke_core.domain import path_claims_boundary as _pb

        class StubResult:
            def __init__(
                self,
                claim_id, declared_paths, touched_paths,
                undeclared_paths,
                status,
            ):
                self.claim_id = claim_id
                self.integration_target = "main"
                self.declared_paths = declared_paths
                self.touched_paths = touched_paths
                self.uncommitted_paths = []
                self.undeclared_paths = undeclared_paths
                self.undeclared_target_ids = []
                self.diagnostics = "stub"
                self.status = status

        # Two claims: A declares foo.py, B declares bar.py; both touched.
        results = {
            1: StubResult(
                1, ["foo.py"], ["foo.py", "bar.py"], ["bar.py"],
                _pb.BoundaryCheckStatus.CONFLICT,
            ),
            2: StubResult(
                2, ["bar.py"], ["foo.py", "bar.py"], ["foo.py"],
                _pb.BoundaryCheckStatus.CONFLICT,
            ),
        }

        def stub_check(conn, *, claim_id, repo_path):
            return results[claim_id]

        monkeypatch.setattr(_pb, "boundary_check_for_claim", stub_check)

        # Seed an item + project + two non-terminal claims.
        repo_root = tmp_path / "repo"
        (repo_root / ".worktrees" / "YOK-9").mkdir(parents=True)

        with init_test_db(
            tmp_path, apply_schema=_make_branch_apply_schema(repo_root)
        ) as db_path:
            # AC-23 expectation: union of declared (foo+bar) covers union
            # of touched (foo+bar), so item-level verdict is accept.
            verdict = _gate.check_boundary_for_item(
                item_id=9,
                target_status="reviewed-implementation",
                db_path=db_path,
            )
            assert verdict is None

    def test_two_claims_union_misses_paths(self, tmp_path, monkeypatch):
        """Two claims, union still missing a touched path — reject."""
        from yoke_core.domain import path_claims_boundary as _pb

        class StubResult:
            def __init__(
                self,
                claim_id, declared_paths, touched_paths,
                undeclared_paths,
                status,
            ):
                self.claim_id = claim_id
                self.integration_target = "main"
                self.declared_paths = declared_paths
                self.touched_paths = touched_paths
                self.uncommitted_paths = []
                self.undeclared_paths = undeclared_paths
                self.undeclared_target_ids = []
                self.diagnostics = "stub"
                self.status = status

        results = {
            1: StubResult(
                1, ["foo.py"], ["foo.py", "bar.py", "rogue.py"],
                ["bar.py", "rogue.py"],
                _pb.BoundaryCheckStatus.CONFLICT,
            ),
            2: StubResult(
                2, ["bar.py"], ["foo.py", "bar.py", "rogue.py"],
                ["foo.py", "rogue.py"],
                _pb.BoundaryCheckStatus.CONFLICT,
            ),
        }

        def stub_check(conn, *, claim_id, repo_path):
            return results[claim_id]

        monkeypatch.setattr(_pb, "boundary_check_for_claim", stub_check)

        repo_root = tmp_path / "repo"
        (repo_root / ".worktrees" / "YOK-9").mkdir(parents=True)

        with init_test_db(
            tmp_path, apply_schema=_make_branch_apply_schema(repo_root)
        ) as db_path:
            verdict = _gate.check_boundary_for_item(
                item_id=9,
                target_status="reviewed-implementation",
                db_path=db_path,
            )
            # Single-aggregate path doesn't cover rogue.py — reject.
            assert verdict is not None
            assert verdict["success"] is False
            assert "GATE_PATH_CLAIM_BOUNDARY" in verdict["error_code"]


class TestAggregationGitignoreFilter:
    """AC-47: aggregation gate honors `.gitignore` for committed paths."""

    def _git(self, repo: Path, *args: str) -> str:
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "test",
            "GIT_COMMITTER_EMAIL": "test@example.com",
        }
        proc = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True, text=True, check=True, env=env,
        )
        return proc.stdout

    def _seed_repo_and_db(self, tmp_path):
        """Real git repo with main + feature branch and a wired-up DB.

        Returns ``(wt_root, apply_schema)`` — the caller opens
        :func:`init_test_db` with the returned strategy so the gate reads the
        same backend DB the closure seeds.
        """
        # The aggregation gate resolves the item worktree under the
        # machine-local project checkout, so the actual git checkout lives at
        # that exact subpath.
        project_root = tmp_path / "demo"
        wt_root = project_root / ".worktrees" / "feature"
        wt_root.mkdir(parents=True)
        self._git(wt_root, "init", "-q", "--initial-branch=main")
        (wt_root / "README.md").write_text("# r\n")
        (wt_root / ".gitignore").write_text("qa-artifacts/\n")
        self._git(wt_root, "add", "README.md", ".gitignore")
        self._git(wt_root, "commit", "-q", "-m", "initial")
        self._git(wt_root, "checkout", "-q", "-b", "feature")

        return wt_root, self._make_apply_schema(project_root)

    @staticmethod
    def _make_apply_schema(project_root: Path):
        """Zero-arg ``apply_schema`` building the full path-claim fixture.

        Runs the production schema-init functions + ``register`` against the
        backend-resolved DB so the same registered claim is visible to the
        gate on the active test database. ``create_core_tables`` prepares the
        catalog surface required by the later steps.
        """

        def _apply() -> None:
            from yoke_core.domain import db_backend
            from yoke_core.domain.actors import seed_canonical_actors
            from yoke_core.domain.events_schema import _create_events_table
            from yoke_core.domain.path_claims import register
            from yoke_core.domain.schema_init_actor_path_claim_tables import (
                create_actor_path_claim_tables,
            )
            from yoke_core.domain.schema_init_path_tables import (
                create_path_registry_tables,
            )
            from yoke_core.domain.schema_init_tables import create_core_tables

            conn = db_backend.connect()
            try:
                create_core_tables(conn)
                _create_events_table(conn)
                create_path_registry_tables(conn)
                create_actor_path_claim_tables(conn)
                seed_canonical_actors(conn)
                actor_row = conn.execute(
                    "SELECT id FROM actors WHERE kind='human' LIMIT 1"
                ).fetchone()
                actor_id = int(actor_row[0])
                conn.execute(
                    "INSERT INTO projects "
                    "(id, slug, name, default_branch, "
                    "public_item_prefix, created_at) "
                    "VALUES (3, 'demo', 'Demo', 'main', 'DMO', %s)",
                    (
                        "2026-05-01T00:00:00Z",
                    ),
                )
                register_machine_checkout(
                    project_root.parent / "machine-config",
                    project_root,
                    3,
                )
                conn.execute(
                    "INSERT INTO items (id, title, type, status, priority, "
                    "created_at, updated_at, project_id, project_sequence, "
                    "worktree) VALUES "
                    "(%s, %s, 'issue', 'idea', 'medium', %s, %s, 3, 701, "
                    "'feature')",
                    (
                        701,
                        "demo",
                        "2026-05-01T00:00:00Z",
                        "2026-05-01T00:00:00Z",
                    ),
                )
                conn.execute(
                    "INSERT INTO path_targets "
                    "(id, project_id, kind, path_string, generation, "
                    "created_at) VALUES (1, 3, 'directory', "
                    "'src/foo.py', 1, '2026-05-01T00:00:00Z')"
                )
                conn.commit()
                register(
                    conn, actor_id=actor_id, integration_target="main",
                    target_ids=[1], item_id=701,
                )
            finally:
                conn.close()

        return _apply

    def test_gate_accepts_when_only_undeclared_paths_are_gitignored(
        self, tmp_path
    ):
        wt_root, apply_schema = self._seed_repo_and_db(tmp_path)
        (wt_root / "src").mkdir(exist_ok=True)
        (wt_root / "src" / "foo.py").write_text("print('x')\n")
        (wt_root / "qa-artifacts").mkdir(exist_ok=True)
        (wt_root / "qa-artifacts" / "shot.png").write_bytes(b"\x89PNG")
        self._git(wt_root, "add", "src/foo.py")
        self._git(wt_root, "add", "-f", "qa-artifacts/shot.png")
        self._git(wt_root, "commit", "-q", "-m", "feat + ignored artifact")
        with init_test_db(tmp_path, apply_schema=apply_schema) as db_path:
            verdict = _gate.check_boundary_for_item(
                item_id=701,
                target_status="reviewed-implementation",
                db_path=db_path,
            )
            assert verdict is None, verdict
