"""Governed migration tests for harness session project identity."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from runtime.api.domain.migrations import harness_session_project_identity as migration
from runtime.api.fixtures.file_test_db import apply_sql_script
from runtime.api.fixtures import pg_testdb
from yoke_core.domain.schema_common import _column_exists, _get_indexes


_BASE_SCHEMA = """
    CREATE TABLE projects (
        id INTEGER PRIMARY KEY,
        slug TEXT NOT NULL,
        name TEXT DEFAULT '',
        emoji TEXT DEFAULT '',
        github_repo TEXT DEFAULT '',
        public_item_prefix TEXT DEFAULT 'YOK'
    );
    CREATE TABLE harness_sessions (
        session_id TEXT PRIMARY KEY,
        executor TEXT NOT NULL,
        provider TEXT NOT NULL,
        model TEXT NOT NULL,
        workspace TEXT NOT NULL,
        offered_at TEXT NOT NULL,
        last_heartbeat TEXT NOT NULL,
        ended_at TEXT
    );
"""


@pytest.fixture
def prestamped_conn() -> Iterator[Any]:
    name = pg_testdb.create_test_database()
    conn = pg_testdb.connect_test_database(name)
    try:
        apply_sql_script(conn, _BASE_SCHEMA)
        conn.execute(
            "INSERT INTO projects (id, slug) VALUES (%s, %s)",
            (1, "yoke"),
        )
        conn.execute(
            "INSERT INTO projects (id, slug) VALUES (%s, %s)",
            (2, "buzz"),
        )
        conn.execute("ALTER TABLE harness_sessions ADD COLUMN project_id INTEGER DEFAULT NULL")
        for session_id, workspace, project_id in (
            ("session-yoke", "workspace-yoke", 1),
            ("session-yoke-worktree", "workspace-yoke-worktree", 1),
            ("session-buzz", "workspace-buzz", 2),
        ):
            _insert_session(conn, session_id, workspace, project_id=project_id)
        conn.commit()
        yield conn
    finally:
        conn.close()
        pg_testdb.drop_test_database(name)


@pytest.fixture
def unresolved_conn() -> Iterator[Any]:
    name = pg_testdb.create_test_database()
    conn = pg_testdb.connect_test_database(name)
    try:
        apply_sql_script(conn, _BASE_SCHEMA)
        conn.execute(
            "INSERT INTO projects (id, slug) VALUES (%s, %s)",
            (1, "yoke"),
        )
        _insert_session(conn, "session-unmapped", "/elsewhere/project")
        conn.commit()
        yield conn
    finally:
        conn.close()
        pg_testdb.drop_test_database(name)


def _insert_session(
    conn: Any,
    session_id: str,
    workspace: str,
    *,
    project_id: int | None = None,
) -> None:
    columns = [
        "session_id",
        "executor",
        "provider",
        "model",
        "workspace",
        "offered_at",
        "last_heartbeat",
        "ended_at",
    ]
    values: list[Any] = [
        session_id,
        "claude-code",
        "anthropic",
        "claude-opus-4-8",
        workspace,
        "2026-06-30T12:00:00Z",
        "2026-06-30T12:00:01Z",
        None,
    ]
    if project_id is not None:
        columns.append("project_id")
        values.append(project_id)
    placeholders = ", ".join("%s" for _ in values)
    conn.execute(
        f"INSERT INTO harness_sessions ({', '.join(columns)}) "
        f"VALUES ({placeholders})",
        values,
    )


def test_enforces_prestamped_rows_and_sets_strict_shape(
    prestamped_conn: Any,
) -> None:
    assert _column_exists(prestamped_conn, "harness_sessions", "project_id")

    migration.apply(prestamped_conn)
    prestamped_conn.commit()

    assert _column_exists(prestamped_conn, "harness_sessions", "project_id")
    assert "idx_harness_sessions_project" in set(
        _get_indexes(prestamped_conn, "harness_sessions")
    )
    rows = prestamped_conn.execute(
        "SELECT session_id, project_id FROM harness_sessions ORDER BY session_id"
    ).fetchall()
    assert {row["session_id"]: row["project_id"] for row in rows} == {
        "session-buzz": 2,
        "session-yoke": 1,
        "session-yoke-worktree": 1,
    }


def test_idempotent_and_invariants_pass(prestamped_conn: Any) -> None:
    migration.apply(prestamped_conn)
    migration.apply(prestamped_conn)
    prestamped_conn.commit()

    migration.invariants(prestamped_conn)


def test_refuses_unstamped_rows(unresolved_conn: Any) -> None:
    with pytest.raises(AssertionError, match="unstamped harness sessions remain"):
        migration.apply(unresolved_conn)
