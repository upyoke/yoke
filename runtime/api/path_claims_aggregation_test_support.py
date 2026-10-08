"""Native git and database fixtures for item path-claim aggregation."""

from __future__ import annotations
import subprocess
from pathlib import Path
from runtime.api.fixtures.machine_config_test import register_machine_checkout


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


class StubResult:
    """One per-claim verdict, so the tests exercise aggregation only."""

    def __init__(
        self,
        claim_id,
        declared_paths,
        touched_paths,
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


def _repo_with_worktree(tmp_path: Path) -> Path:
    """A real git repo on ``main`` plus the item's worktree directory.

    These tests stub the per-claim check, but the gate still resolves
    which rung of the integration ladder it may diff against before
    running any check — so the fixture needs a trunk that resolves.
    """
    repo_root = tmp_path / "repo"
    (repo_root / ".worktrees" / "YOK-9").mkdir(parents=True)
    _git(repo_root, "init", "-q", "--initial-branch=main")
    (repo_root / "README.md").write_text("# repo\n")
    _git(repo_root, "add", "README.md")
    _git(
        repo_root,
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@x",
        "commit",
        "-q",
        "-m",
        "initial",
    )
    return repo_root


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
                "CREATE TABLE items (id INTEGER PRIMARY KEY, project_id INTEGER)"
            )
            conn.execute(
                "CREATE TABLE item_worktrees ("
                "id INTEGER PRIMARY KEY, item_id INTEGER NOT NULL, "
                "branch TEXT NOT NULL, path TEXT, lane_role TEXT NOT NULL, "
                "state TEXT NOT NULL, created_at TEXT NOT NULL, "
                "updated_at TEXT NOT NULL, released_at TEXT)"
            )
            conn.execute(
                "CREATE TABLE projects (id INTEGER PRIMARY KEY, slug TEXT UNIQUE)"
            )
            conn.execute(
                "CREATE TABLE path_claims ("
                "id INTEGER PRIMARY KEY, owner_kind TEXT, "
                "owner_item_id INTEGER, state TEXT, "
                "integration_target TEXT)"
            )
            conn.execute(
                "INSERT INTO projects (id, slug) VALUES (3, 'demo')",
            )
            register_machine_checkout(repo_root.parent / "machine-config", repo_root, 3)
            conn.execute("INSERT INTO items VALUES (9, 3)")
            conn.execute(
                "INSERT INTO item_worktrees VALUES "
                "(1, 9, 'YOK-9', %s, 'implementation', 'active', "
                "'2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z', NULL)",
                (str(repo_root / ".worktrees" / "YOK-9"),),
            )
            conn.execute(
                "INSERT INTO path_claims "
                "(id, owner_kind, owner_item_id, state, integration_target) "
                "VALUES (1, 'item', 9, 'active', 'main')"
            )
            conn.execute(
                "INSERT INTO path_claims "
                "(id, owner_kind, owner_item_id, state, integration_target) "
                "VALUES (2, 'item', 9, 'active', 'main')"
            )
            conn.commit()
        finally:
            conn.close()

    return _apply
