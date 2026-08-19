"""Shared ``db_path`` fixture for the deployment-runs test modules.

Used by ``test_deployment_runs.py``, ``test_deployment_runs_lineage_qa.py``,
and ``test_deployment_runs_preview.py``. No tests live here — the lack of
a ``test_`` prefix keeps pytest from collecting it.

The fixture builds a temp DB with the minimal schema (projects,
deployment_flows, items, item_dependencies) needed for the deployment-runs
domain, then runs ``cmd_init`` to create the deployment tables. It routes
through :func:`runtime.api.fixtures.file_test_db.init_test_db` so the same
body runs against one disposable per-test Postgres database. The minimal schema
and ``cmd_init`` both resolve their connection through the backend factory, so
everything lands in the one repointed authority.
"""

from __future__ import annotations

from typing import Iterator
from pathlib import Path

import pytest

from yoke_core.domain import deployment_runs as dr
from runtime.api.fixtures.file_test_db import apply_inline_ddl, init_test_db

_MINIMAL_SCHEMA_DDL = """
    CREATE TABLE IF NOT EXISTS projects (
        id INTEGER PRIMARY KEY,
        slug TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL DEFAULT '',
        public_item_prefix TEXT NOT NULL DEFAULT 'YOK'
    );
    INSERT INTO projects (id, slug, name) VALUES (1, 'yoke', 'Yoke');
    INSERT INTO projects (id, slug, name) VALUES (2, 'externalwebapp', 'ExternalWebapp');

    CREATE TABLE IF NOT EXISTS sites (
        id INTEGER PRIMARY KEY,
        project_id INTEGER NOT NULL REFERENCES projects(id),
        name TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT '',
        settings TEXT DEFAULT '{}',
        UNIQUE(id, project_id),
        UNIQUE(project_id, name)
    );
    INSERT INTO sites (id, project_id, name) VALUES (101, 1, 'yoke');
    CREATE TABLE IF NOT EXISTS environments (
        id INTEGER PRIMARY KEY,
        site INTEGER NOT NULL,
        project_id INTEGER NOT NULL REFERENCES projects(id),
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
    VALUES (202, 101, 1, 'stage');
    CREATE TABLE IF NOT EXISTS deployment_flows (
        id TEXT PRIMARY KEY,
        project_id INTEGER NOT NULL REFERENCES projects(id),
        name TEXT,
        stages TEXT,
        target_tier TEXT,
        target_environment_id INTEGER REFERENCES environments(id),
        status TEXT NOT NULL DEFAULT 'active'
    );
    INSERT INTO deployment_flows
        (id, project_id, name, stages, target_tier, target_environment_id)
    VALUES ('flow-main', 1, 'Main Flow',
            '[{"name":"merged"},{"name":"deployed"},{"name":"complete"}]',
            'persistent', 201);
    INSERT INTO deployment_flows
        (id, project_id, name, stages, target_tier, target_environment_id)
    VALUES ('flow-preview', 1, 'Preview Flow',
            '[{"name":"preview-deploy"},{"name":"preview-verify"}]',
            NULL, NULL);

    CREATE TABLE IF NOT EXISTS items (
        id INTEGER PRIMARY KEY,
        title TEXT,
        status TEXT DEFAULT 'idea',
        project_id INTEGER NOT NULL DEFAULT 1 REFERENCES projects(id),
        project_sequence INTEGER NOT NULL DEFAULT 0,
        deployment_flow TEXT,
        merged_at TEXT
    );

    CREATE TABLE IF NOT EXISTS item_dependencies (
        id INTEGER PRIMARY KEY,
        dependent_item_id INTEGER NOT NULL,
        blocking_item_id INTEGER NOT NULL,
        satisfaction TEXT DEFAULT 'status:done'
    );
"""


def _apply_schema() -> None:
    """``init_test_db`` strategy: minimal schema + deployment-run tables.

    Resolves its connection through the backend factory with ``YOKE_PG_DSN``
    repointed to the disposable per-test Postgres database.
    """
    apply_inline_ddl(_MINIMAL_SCHEMA_DDL)
    dr.cmd_init()


@pytest.fixture()
def db_path(tmp_path: Path) -> Iterator[str]:
    """Create a temp DB with the minimal schema needed for deployment runs."""
    with init_test_db(tmp_path, apply_schema=_apply_schema) as path:
        yield path
