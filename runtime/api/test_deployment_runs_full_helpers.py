"""Shared fixture + helpers for deployment_runs full pytest suite.

Provides the ``db_path`` fixture (temp DB seeded with projects, flows, items
schema) and a ``_conn`` helper. Imported via ``from runtime.api.\
test_deployment_runs_full_helpers import db_path  # noqa: F401`` from each
sibling test module.

The module name is intentionally ``test_*`` so it sits next to the test
files; it has no test_ functions, so pytest collects nothing from it.
"""

from __future__ import annotations

from typing import Iterator
from pathlib import Path

import pytest

from yoke_core.domain import deployment_runs as dr
from yoke_core.domain import db_backend
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl

_SCHEMA_DDL = """
    CREATE TABLE IF NOT EXISTS projects (
        id INTEGER PRIMARY KEY,
        slug TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL DEFAULT '',
        public_item_prefix TEXT NOT NULL DEFAULT 'YOK'
    );
    INSERT INTO projects (id, slug, name) VALUES (1, 'yoke', 'yoke');
    INSERT INTO projects (id, slug, name) VALUES (2, 'buzz', 'buzz');

    CREATE TABLE IF NOT EXISTS deployment_flows (
        id TEXT PRIMARY KEY,
        project_id INTEGER NOT NULL,
        name TEXT,
        stages TEXT,
        target_env TEXT,
        done_description TEXT
    );
    INSERT INTO deployment_flows (id, project_id, name, stages, target_env)
        VALUES ('yoke-internal', 1, 'yoke-internal', '[]', NULL);
    INSERT INTO deployment_flows (id, project_id, name, stages, target_env)
        VALUES ('buzz-standard', 2, 'buzz-standard',
                '[{"name":"preview"},{"name":"production"}]', 'preview');

    CREATE TABLE IF NOT EXISTS items (
        id INTEGER PRIMARY KEY,
        title TEXT NOT NULL DEFAULT '',
        type TEXT NOT NULL DEFAULT 'issue',
        status TEXT NOT NULL DEFAULT 'idea',
        priority TEXT NOT NULL DEFAULT 'medium',
        project_id INTEGER NOT NULL DEFAULT 1,
        project_sequence INTEGER NOT NULL DEFAULT 0,
        deployment_flow TEXT,
        merged_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        source TEXT NOT NULL DEFAULT '2',
        deploy_stage TEXT
    );

    CREATE TABLE IF NOT EXISTS item_dependencies (
        id INTEGER PRIMARY KEY,
        dependent_item TEXT NOT NULL,
        blocking_item TEXT NOT NULL,
        gate_point TEXT NOT NULL DEFAULT 'activation',
        satisfaction TEXT NOT NULL DEFAULT 'status:done',
        source TEXT NOT NULL DEFAULT 'test',
        rationale TEXT NOT NULL DEFAULT '',
        evidence_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        UNIQUE(dependent_item, blocking_item, gate_point)
    );
"""


def _apply_schema() -> None:
    """``init_test_db`` strategy: full deployment-runs schema + cmd_init.

    Resolves its connection through the backend factory with ``YOKE_PG_DSN``
    repointed to the disposable per-test Postgres database.
    """
    from yoke_core.domain import db_backend

    conn = db_backend.connect()
    try:
        apply_fixture_ddl(conn, _SCHEMA_DDL)
    finally:
        conn.close()
    dr.cmd_init()


@pytest.fixture()
def db_path(tmp_path: Path) -> Iterator[str]:
    """Create a temp DB with the schema needed for deployment runs."""
    with init_test_db(tmp_path, apply_schema=_apply_schema) as path:
        yield path


def _conn(db_path: str):
    """Helper to open a backend-aware connection.

    The Postgres facade returns positionally-indexable rows. The test bodies
    read rows by index (``.fetchone()[0]``), so the fixture does not need a row
    factory tweak.
    """
    return connect_test_db(db_path)


def _placeholder(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"
