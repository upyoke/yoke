"""Tests for :mod:`yoke_core.domain.projects_trunk`.

Covers AC-7 fallback behavior: read ``projects.default_branch`` and
fall back to ``"main"`` when the value is missing or blank.
"""

from __future__ import annotations

from typing import Any, Iterator

import pytest

from runtime.api.fixtures import pg_testdb
from yoke_core.domain.projects_trunk import (
    DEFAULT_TRUNK,
    ProjectNotFound,
    resolve_trunk,
    resolve_trunk_safe,
)


def _empty_db_conn() -> Any:
    name = pg_testdb.create_test_database()
    return pg_testdb.drop_database_on_close(
        pg_testdb.connect_test_database(name), name,
    )


@pytest.fixture
def conn() -> Iterator[Any]:
    c = _empty_db_conn()
    c.execute(
        "CREATE TABLE projects (id INTEGER PRIMARY KEY, slug TEXT UNIQUE, "
        "default_branch TEXT DEFAULT 'main')"
    )
    yield c
    c.close()


def test_default_trunk_constant_is_main():
    assert DEFAULT_TRUNK == "main"


def test_resolve_trunk_reads_configured_value(conn):
    conn.execute(
        "INSERT INTO projects (id, slug, default_branch) VALUES (100, 'alpha', 'trunk')"
    )
    assert resolve_trunk(conn, 100) == "trunk"


def test_resolve_trunk_returns_main_when_column_is_null(conn):
    conn.execute(
        "INSERT INTO projects (id, slug, default_branch) VALUES (100, 'alpha', NULL)"
    )
    assert resolve_trunk(conn, 100) == "main"


def test_resolve_trunk_returns_main_when_value_is_blank(conn):
    conn.execute(
        "INSERT INTO projects (id, slug, default_branch) VALUES (100, 'alpha', '   ')"
    )
    assert resolve_trunk(conn, 100) == "main"


def test_resolve_trunk_raises_when_project_row_missing(conn):
    with pytest.raises(ProjectNotFound):
        resolve_trunk(conn, 999)


def test_resolve_trunk_safe_returns_none_when_project_row_missing(conn):
    assert resolve_trunk_safe(conn, 999) is None


def test_resolve_trunk_safe_returns_main_on_null_column(conn):
    conn.execute(
        "INSERT INTO projects (id, slug, default_branch) VALUES (100, 'alpha', NULL)"
    )
    assert resolve_trunk_safe(conn, 100) == "main"


def test_resolve_trunk_safe_returns_value_when_set(conn):
    conn.execute(
        "INSERT INTO projects (id, slug, default_branch) VALUES (100, 'alpha', 'develop')"
    )
    assert resolve_trunk_safe(conn, 100) == "develop"


def test_resolve_trunk_strips_whitespace(conn):
    conn.execute(
        "INSERT INTO projects (id, slug, default_branch) VALUES (100, 'alpha', '  trunk  ')"
    )
    assert resolve_trunk(conn, 100) == "trunk"


def test_resolve_trunk_safe_returns_none_when_projects_table_missing():
    c = _empty_db_conn()
    try:
        assert resolve_trunk_safe(c, 100) is None
    finally:
        c.close()


def test_resolve_trunk_raises_project_not_found_when_table_missing():
    c = _empty_db_conn()
    try:
        with pytest.raises(ProjectNotFound):
            resolve_trunk(c, 100)
    finally:
        c.close()
