"""Shared fixtures for ``test_check_path_claim_coverage_at_commit*``.

Holds the disposable-Postgres ``path_claims`` schema seed and the git-repo
init helpers so the test file proper stays under the 350-line cap.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from yoke_core.domain.lint_worktree_path_invariants import (
    WorktreeInvariantContext,
)

_SCHEMA_DDL = """
CREATE TABLE path_claims (
    id INTEGER PRIMARY KEY,
    item_id INTEGER NOT NULL,
    state TEXT NOT NULL
);
CREATE TABLE path_claim_targets (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    claim_id INTEGER NOT NULL,
    target_id INTEGER NOT NULL
);
CREATE TABLE path_targets (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    path_string TEXT NOT NULL
);
"""


@pytest.fixture
def conn():
    """Disposable Postgres DB with the minimal schema for the active-claim lookup."""
    from runtime.api.fixtures import pg_testdb
    from runtime.api.fixtures.schema_ddl import apply_fixture_ddl

    name = pg_testdb.create_test_database()
    c = pg_testdb.drop_database_on_close(
        pg_testdb.connect_test_database(name), name
    )
    apply_fixture_ddl(c, _SCHEMA_DDL)
    yield c
    c.close()


def seed_target(conn, path: str) -> int:
    cur = conn.execute(
        "INSERT INTO path_targets (path_string) VALUES (%s) RETURNING id", (path,),
    )
    return int(cur.fetchone()[0])


def seed_claim(
    conn,
    *,
    claim_id: int,
    item_id: int,
    state: str,
    paths: list[str],
) -> None:
    conn.execute(
        "INSERT INTO path_claims (id, item_id, state) VALUES (%s, %s, %s)",
        (claim_id, item_id, state),
    )
    for p in paths:
        target_id = seed_target(conn, p)
        conn.execute(
            "INSERT INTO path_claim_targets (claim_id, target_id) "
            "VALUES (%s, %s)",
            (claim_id, target_id),
        )
    conn.commit()


def init_repo(repo: Path) -> None:
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(repo)], check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "t@example.com"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "test"], check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "commit.gpgsign", "false"],
        check=True,
    )


def stage_file(repo: Path, relpath: str, content: str = "x") -> None:
    full = repo / relpath
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content, encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", relpath], check=True)


def make_ctx(
    *,
    item_id: int | None,
    inside: bool,
    root: str = "/repo/.worktrees/item-worktree",
) -> WorktreeInvariantContext:
    return WorktreeInvariantContext(
        session_id="sess",
        item_id=item_id,
        worktree_branch=f"YOK-{item_id}" if item_id else None,
        expected_worktree_root=root if inside and item_id else None,
        actual_cwd=root,
        is_inside_worktree=inside,
    )
