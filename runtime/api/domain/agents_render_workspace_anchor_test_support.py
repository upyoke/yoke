"""Database and subprocess support for workspace-anchored render tests."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from runtime.api.fixtures.file_test_db import connect_test_db
from runtime.api.fixtures.machine_config_test import register_machine_checkout
from yoke_core.domain import db_backend
from yoke_core.domain.agents_render_workspace import BOUND_WORKSPACE_ENV_VAR
from yoke_core.domain.schema_init_apply import execute_schema_script


SESSION_REGRESSION = "test-sess-yok-1784"
_IDENTITY_TEST_TARGETS = (
    "test_byte_identity",
    "test_all_agents_renderable",
    "test_no_rendered_agent_uses_retired_backlog_md_paths",
)
_WORKSPACE_CLAIM_SCHEMA = """
CREATE TABLE projects (id INTEGER PRIMARY KEY, slug TEXT UNIQUE);
CREATE TABLE items (
    id INTEGER PRIMARY KEY, project_id INTEGER
);
CREATE TABLE item_worktrees (
    id INTEGER PRIMARY KEY, item_id INTEGER NOT NULL,
    branch TEXT NOT NULL, path TEXT, lane_role TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, released_at TEXT
);
CREATE TABLE epic_tasks (
    epic_id INTEGER NOT NULL, task_num INTEGER NOT NULL,
    item_worktree_id INTEGER, PRIMARY KEY (epic_id, task_num)
);
CREATE TABLE work_claims (
    id INTEGER PRIMARY KEY, session_id TEXT, target_kind TEXT,
    item_id INTEGER, epic_id INTEGER, task_num INTEGER,
    process_key TEXT, released_at TEXT
);
"""


def run_identity_pytest(*, cwd: Path, repo_root: Path) -> tuple[int, str]:
    """Run the workspace byte-identity tests from a selected directory."""
    test_target = repo_root / "runtime/api/domain/test_agents_render.py"
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "--no-header",
        "--rootdir",
        str(repo_root),
        "-k",
        " or ".join(_IDENTITY_TEST_TARGETS),
        str(test_target),
    ]
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(repo_root) + (
        os.pathsep + environment["PYTHONPATH"] if environment.get("PYTHONPATH") else ""
    )
    environment[BOUND_WORKSPACE_ENV_VAR] = str(repo_root)
    completed = subprocess.run(
        command,
        cwd=str(cwd),
        env=environment,
        capture_output=True,
        text=True,
        timeout=180,
    )
    return completed.returncode, completed.stdout + completed.stderr


def apply_workspace_claim_schema() -> None:
    """Build the claim schema against the backend-resolved test database."""
    connection = db_backend.connect()
    try:
        execute_schema_script(connection, _WORKSPACE_CLAIM_SCHEMA)
        connection.commit()
    finally:
        connection.close()


def _placeholder(connection) -> str:
    return "%s" if db_backend.connection_is_postgres(connection) else "?"


def seed_worktree_claim_rows(
    db_path: str,
    *,
    repo_root: Path,
    config_root: Path,
    branch: str,
    session_id: str,
) -> None:
    """Seed one project, worktree-bearing item, and active item work claim."""
    connection = connect_test_db(db_path)
    placeholder = _placeholder(connection)
    connection.execute(
        f"INSERT INTO projects (id, slug) VALUES ({placeholder}, {placeholder})",
        (1, "yoke"),
    )
    register_machine_checkout(config_root, repo_root, 1)
    connection.execute(
        f"INSERT INTO items (id, project_id) VALUES ({placeholder}, {placeholder})",
        (1784, 1),
    )
    connection.execute(
        "INSERT INTO item_worktrees "
        "(item_id, branch, lane_role, state, created_at, updated_at) "
        f"VALUES ({placeholder}, {placeholder}, 'implementation', 'active', "
        f"{placeholder}, {placeholder})",
        (
            1784,
            branch,
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:00:00Z",
        ),
    )
    connection.execute(
        "INSERT INTO work_claims (session_id, target_kind, item_id) "
        f"VALUES ({placeholder}, 'item', {placeholder})",
        (session_id, 1784),
    )
    connection.commit()
    connection.close()
