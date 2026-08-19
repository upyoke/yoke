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
from runtime.api.api_workflow_test_helpers import (
    install_workflow_registry_and_pin_items,
)
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
    INSERT INTO projects (id, slug, name) VALUES (2, 'externalwebapp', 'externalwebapp');

    CREATE TABLE IF NOT EXISTS sites (
        id INTEGER PRIMARY KEY,
        project_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT '',
        settings TEXT DEFAULT '{}',
        UNIQUE(id, project_id),
        UNIQUE(project_id, name)
    );
    INSERT INTO sites (id, project_id, name)
        VALUES (101, 1, 'yoke');
    INSERT INTO sites (id, project_id, name)
        VALUES (102, 2, 'externalwebapp');
    CREATE TABLE IF NOT EXISTS environments (
        id INTEGER PRIMARY KEY,
        site INTEGER NOT NULL,
        project_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        url TEXT,
        last_deployed_at TEXT,
        created_at TEXT NOT NULL DEFAULT '',
        settings TEXT DEFAULT '{}',
        UNIQUE(project_id, name),
        FOREIGN KEY(site, project_id) REFERENCES sites(id, project_id)
    );
    INSERT INTO environments (id, site, project_id, name)
        VALUES (201, 101, 1, 'prod');
    INSERT INTO environments (id, site, project_id, name)
        VALUES (202, 102, 2, 'preview');
    INSERT INTO environments (id, site, project_id, name)
        VALUES (203, 102, 2, 'prod');
    CREATE TABLE IF NOT EXISTS deployment_flows (
        id TEXT PRIMARY KEY,
        project_id INTEGER NOT NULL,
        name TEXT,
        stages TEXT,
        target_tier TEXT,
        target_environment_id INTEGER,
        done_description TEXT,
        status TEXT NOT NULL DEFAULT 'active'
    );
    INSERT INTO deployment_flows
        (id, project_id, name, stages, target_tier, target_environment_id)
        VALUES ('yoke-internal', 1, 'yoke-internal', '[]', NULL, NULL);
    INSERT INTO deployment_flows
        (id, project_id, name, stages, target_tier, target_environment_id)
        VALUES ('externalwebapp-standard', 2, 'externalwebapp-standard',
                '[{"name":"preview"},{"name":"prod"}]',
                'persistent', 202);

    CREATE TABLE IF NOT EXISTS items (
        id INTEGER PRIMARY KEY,
        title TEXT NOT NULL DEFAULT '',
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
        dependent_item_id INTEGER NOT NULL,
        blocking_item_id INTEGER NOT NULL,
        gate_point TEXT NOT NULL DEFAULT 'activation',
        satisfaction TEXT NOT NULL DEFAULT 'status:done',
        source TEXT NOT NULL DEFAULT 'test',
        rationale TEXT NOT NULL DEFAULT '',
        evidence_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        UNIQUE(dependent_item_id, blocking_item_id, gate_point)
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
        install_workflow_registry_and_pin_items(conn)
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


def _insert_delivery_ready_item(db_path: str, item_id: int) -> None:
    from yoke_core.domain.workflow_registry import resolve_current_workflow_pin

    conn = _conn(db_path)
    try:
        workflow_id, workflow_version_id = resolve_current_workflow_pin(
            conn,
            "issue",
        )
        conn.execute(
            "INSERT INTO items ("
            "id, title, workflow_id, workflow_version_id, status, "
            "project_id, project_sequence, deployment_flow, "
            "created_at, updated_at"
            ") VALUES ("
            "%s, 'deployment member', %s, %s, 'implemented', "
            "1, %s, 'yoke-internal', "
            "'2026-07-28T00:00:00Z', '2026-07-28T00:00:00Z'"
            ")",
            (item_id, workflow_id, workflow_version_id, item_id),
        )
        conn.commit()
    finally:
        conn.close()
