"""Shared helpers and fixtures for the worktree pytest suites.

Split out of the original ``test_worktree.py`` so each authored test file
stays under the 350-line limit. Lives outside the ``test_*.py`` collection
pattern so pytest does not pick it up as a test module.
"""

from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path
from typing import Iterator

import pytest

from yoke_core.domain import db_backend
from yoke_core.domain.project_seed_test_helpers import SEED_PROJECT_IDS
from yoke_core.domain.schema_init_apply import execute_schema_script
from runtime.api.fixtures.file_test_db import init_test_db


TEST_ITEM_ID = 42
TEST_ITEM_REF = f"YOK-{TEST_ITEM_ID}"


# ---------------------------------------------------------------------------
# Minimal-schema strategy for ``init_test_db``
# ---------------------------------------------------------------------------

# The worktree suites use a compact current-schema subset; routing
# through the backend factory (``db_backend.connect()``) lands the schema on
# the repointed per-test Postgres DB.
_YOKE_DB_DDL = textwrap.dedent("""\
    CREATE TABLE IF NOT EXISTS projects (
        id INTEGER PRIMARY KEY,
        slug TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL,
        default_branch TEXT DEFAULT 'main',
        github_repo TEXT,
        public_item_prefix TEXT NOT NULL DEFAULT 'YOK',
        created_at TEXT DEFAULT '2026-01-01T00:00:00Z'
    );
    CREATE TABLE IF NOT EXISTS items (
        id INTEGER PRIMARY KEY,
        title TEXT,
        type TEXT DEFAULT 'issue',
        status TEXT DEFAULT 'idea',
        priority TEXT DEFAULT 'medium',
        project_id INTEGER NOT NULL DEFAULT 1 REFERENCES projects(id),
        project_sequence INTEGER NOT NULL,
        created_at TEXT DEFAULT '2026-01-01T00:00:00Z',
        updated_at TEXT DEFAULT '2026-01-01T00:00:00Z',
        UNIQUE(project_id, project_sequence)
    );
    CREATE TABLE IF NOT EXISTS epic_tasks (
        id INTEGER PRIMARY KEY,
        epic_id INTEGER NOT NULL,
        task_num INTEGER NOT NULL,
        title TEXT,
        status TEXT,
        item_worktree_id INTEGER,
        UNIQUE(epic_id, task_num)
    );
    CREATE TABLE IF NOT EXISTS epic_dispatch_chains (
        id INTEGER PRIMARY KEY,
        epic_id INTEGER NOT NULL,
        item_worktree_id INTEGER,
        queue TEXT,
        current_index INTEGER DEFAULT 0,
        current_task TEXT,
        UNIQUE(epic_id, item_worktree_id)
    );
""")


def apply_yoke_db_schema() -> None:
    """``apply_schema`` strategy seeding the minimal ``items`` + ``projects`` DDL.

    Resolves its connection through the backend factory with ``YOKE_PG_DSN``
    repointed to the disposable per-test Postgres database.
    """
    conn = db_backend.connect()
    try:
        execute_schema_script(conn, _YOKE_DB_DDL)
        from yoke_core.domain.item_worktree_schema import (
            ensure_item_worktree_schema,
        )
        from yoke_core.domain.workflow_registry import converge_builtin_workflows
        from yoke_core.domain.workflow_schema import ensure_workflow_schema

        ensure_item_worktree_schema(conn)
        ensure_workflow_schema(conn)
        converge_builtin_workflows(conn)
        p = "%s" if db_backend.connection_is_postgres(conn) else "?"
        conn.execute(
            "INSERT INTO projects "
            "(id, slug, name, created_at) "
            f"VALUES ({p}, {p}, {p}, {p}) "
            "ON CONFLICT(id) DO NOTHING",
            (
                SEED_PROJECT_IDS["yoke"],
                "yoke",
                "Yoke",
                "2026-01-01T00:00:00Z",
            ),
        )
        conn.execute(
            "INSERT INTO projects "
            "(id, slug, name, created_at) "
            f"VALUES ({p}, {p}, {p}, {p}) "
            "ON CONFLICT(id) DO NOTHING",
            (
                SEED_PROJECT_IDS["externalwebapp"],
                "externalwebapp",
                "ExternalWebapp",
                "2026-01-01T00:00:00Z",
            ),
        )
        conn.commit()
    finally:
        conn.close()


def pin_test_item_workflow(conn, item_id: int, workflow_id: str) -> None:
    """Attach the current immutable workflow version to a seeded item."""
    from yoke_core.domain.workflow_registry import resolve_current_workflow_pin

    _, version_id = resolve_current_workflow_pin(conn, workflow_id)
    conn.execute(
        "UPDATE items SET workflow_id = %s, workflow_version_id = %s "
        "WHERE id = %s",
        (workflow_id, version_id, item_id),
    )


@pytest.fixture
def git_repo(tmp_path):
    """Create a minimal git repo with an initial commit."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=str(repo), check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(repo), check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(repo), check=True)
    subprocess.run(["git", "checkout", "-qb", "main"], cwd=str(repo), check=True,
                    capture_output=True)
    (repo / "README.md").write_text("init\n")
    subprocess.run(["git", "add", "README.md"], cwd=str(repo), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=str(repo), check=True,
                    capture_output=True)

    # Create the runtime/config compatibility fixture used by worktree tests.
    (repo / "runtime").mkdir()
    (repo / "runtime" / "config").write_text("worktrees_dir=.worktrees\n")

    return repo


@pytest.fixture
def yoke_db(tmp_path: Path) -> Iterator[str]:
    """Yield a minimal current-schema worktree database on either backend.

    ``init_test_db`` provisions a disposable per-test Postgres database and
    repoints YOKE_PG_DSN at it for the context's lifetime, so backend-routed
    production reads (``db_helpers.connect()``) land in the same DB the seeds
    write to. The yielded token is the file-shaped test handle threaded through
    code-under-test; the connection target is the DSN.
    """
    with init_test_db(tmp_path, apply_schema=apply_yoke_db_schema) as db_path:
        yield db_path
