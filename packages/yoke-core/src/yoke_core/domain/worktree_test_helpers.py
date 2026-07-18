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

# The worktree suites only need the ``items`` + ``projects`` tables; routing
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
        worktree TEXT,
        project_id INTEGER NOT NULL DEFAULT 1 REFERENCES projects(id),
        project_sequence INTEGER NOT NULL,
        created_at TEXT DEFAULT '2026-01-01T00:00:00Z',
        updated_at TEXT DEFAULT '2026-01-01T00:00:00Z',
        UNIQUE(project_id, project_sequence)
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
    """Yield a minimal yoke.db (``items`` + ``projects``) on either backend.

    ``init_test_db`` provisions a disposable per-test Postgres database and
    repoints YOKE_PG_DSN at it for the context's lifetime, so backend-routed
    production reads (``db_helpers.connect()``) land in the same DB the seeds
    write to. The yielded token is the file-shaped test handle threaded through
    code-under-test; the connection target is the DSN.
    """
    with init_test_db(tmp_path, apply_schema=apply_yoke_db_schema) as db_path:
        yield db_path
