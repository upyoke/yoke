"""Reference-database fixture for public item-reference parser tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


def _seed_refs(connection) -> None:
    connection.execute(
        """
        CREATE TABLE projects (
            id BIGINT PRIMARY KEY,
            slug TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            public_item_prefix TEXT NOT NULL DEFAULT 'TST'
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE items (
            id BIGINT PRIMARY KEY,
            project_id BIGINT NOT NULL REFERENCES projects(id),
            project_sequence BIGINT NOT NULL,
            UNIQUE(project_id, project_sequence)
        )
        """
    )
    connection.execute(
        "INSERT INTO projects (id, slug, name, public_item_prefix) "
        "VALUES (1, 'alpha', 'Alpha', 'TST'), "
        "(2, 'beta', 'Beta', 'EXT'), (3, 'yoke', 'Yoke', 'YOK')"
    )
    connection.execute(
        "INSERT INTO items (id, project_id, project_sequence) "
        "VALUES (1001, 1, 42), (2001, 2, 42), (3001, 3, 42)"
    )
    connection.execute(
        """
        CREATE TABLE harness_sessions (
            session_id TEXT PRIMARY KEY,
            current_item_id TEXT,
            recent_item_id TEXT
        )
        """
    )
    connection.commit()


@pytest.fixture
def ref_db(tmp_path: Path):
    """Yield a database containing three project-local public item refs."""
    with init_test_db(tmp_path, apply_schema=lambda: None) as db_path:
        connection = connect_test_db(db_path)
        try:
            _seed_refs(connection)
        finally:
            connection.close()
        yield db_path
