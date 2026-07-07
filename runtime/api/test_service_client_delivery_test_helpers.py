# lint:no-tmp-runtime-import-check  (worktree lives under /tmp by YOK-1888 dispatch design; this is an in-tree runtime/api/ test file where `from runtime.*` resolves at pytest time)
"""Shared mutation-DB fixture for service_client delivery tests.

Imported by ``test_service_client_delivery.py`` (create-item) and
``test_service_client_delivery_update.py`` (update-item).

The fixture routes through :func:`init_test_db`, which provisions a disposable
per-test database with ``YOKE_PG_DSN`` repointed at it for the fixture's
lifetime. The ``_run_client`` subprocess and the fixture's own seeds hit the
same database. The custom inline mutation schema is applied through the
backend factory via an ``apply_schema`` closure.
"""

from __future__ import annotations

import json

import pytest

from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl

_SCHEMA_DDL = """
    CREATE TABLE projects (
        id INTEGER PRIMARY KEY,
        slug TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL DEFAULT '',
        public_item_prefix TEXT NOT NULL DEFAULT 'YOK'
    );

    INSERT INTO projects (id, slug, name) VALUES (1, 'yoke', 'Yoke');
    INSERT INTO projects (id, slug, name) VALUES (2, 'buzz', 'Buzz');

    CREATE TABLE items (
        id INTEGER PRIMARY KEY,
        title TEXT NOT NULL,
        type TEXT NOT NULL DEFAULT 'issue',
        status TEXT NOT NULL DEFAULT 'idea',
        priority TEXT NOT NULL DEFAULT 'medium',
        flow TEXT DEFAULT 'accelerated',
        rework_count INTEGER DEFAULT 0,
        frozen INTEGER DEFAULT 0,
        github_issue TEXT,
        deployed_to TEXT,
        worktree TEXT,
        merged_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        source TEXT NOT NULL DEFAULT '2',
        project_id INTEGER NOT NULL DEFAULT 1,
        deployment_flow TEXT,
        deploy_stage TEXT
    );

    CREATE TABLE deployment_flows (
        id TEXT PRIMARY KEY,
        project_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        description TEXT,
        stages TEXT NOT NULL,
        on_failure TEXT DEFAULT 'halt',
        created_at TEXT NOT NULL,
        target_env TEXT DEFAULT NULL,
        done_description TEXT DEFAULT NULL,
        UNIQUE(project_id, name)
    );

    CREATE TABLE epic_tasks (
        id INTEGER PRIMARY KEY,
        epic_id INTEGER NOT NULL,
        task_num INTEGER NOT NULL,
        title TEXT NOT NULL,
        status TEXT DEFAULT 'ready',
        body TEXT,
        dependencies TEXT,
        milestone TEXT DEFAULT 'M',
        dispatched INTEGER DEFAULT 0,
        UNIQUE(epic_id, task_num)
    );

    CREATE TABLE qa_requirements (
        id INTEGER PRIMARY KEY,
        item_id INTEGER,
        epic_id INTEGER,
        task_num INTEGER,
        qa_kind TEXT NOT NULL,
        qa_phase TEXT NOT NULL DEFAULT 'verification',
        success_policy TEXT NOT NULL DEFAULT 'blocking'
    );

    CREATE TABLE qa_runs (
        id INTEGER PRIMARY KEY,
        qa_requirement_id INTEGER NOT NULL,
        executor_type TEXT,
        verdict TEXT,
        raw_result TEXT
    );

    CREATE TABLE deployment_runs (
        id TEXT PRIMARY KEY,
        project_id INTEGER NOT NULL,
        flow TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'created',
        current_stage TEXT,
        created_at TEXT NOT NULL,
        started_at TEXT,
        completed_at TEXT,
        created_by TEXT,
        target_env TEXT,
        release_lineage TEXT
    );

    CREATE TABLE deployment_run_items (
        run_id TEXT NOT NULL,
        item_id INTEGER NOT NULL,
        added_at TEXT NOT NULL,
        PRIMARY KEY (run_id, item_id)
    );

    CREATE TABLE project_capabilities (
        id INTEGER PRIMARY KEY,
        project_id INTEGER NOT NULL,
        type TEXT NOT NULL,
        config TEXT,
        settings TEXT
    );
"""


def _apply_mutation_schema() -> None:
    """``init_test_db`` strategy: the custom inline mutation schema.

    Resolves its connection through the backend factory against the repointed
    ``YOKE_PG_DSN``.
    """
    from yoke_core.domain import db_backend

    conn = db_backend.connect()
    try:
        apply_fixture_ddl(conn, _SCHEMA_DDL)
    finally:
        conn.close()


def _seed(db_path: str) -> None:
    """Seed the backend-resolved mutation DB with the fixture rows."""
    conn = connect_test_db(db_path)
    try:
        stages_json = json.dumps([
            {"name": "merged", "executor": "auto"},
            {"name": "approve-deploy", "executor": "human-approval"},
            {"name": "prod-deploy", "executor": "github-actions-workflow"},
            {"name": "complete", "executor": "auto"},
        ])
        conn.execute(
            """INSERT INTO deployment_flows (id, project_id, name, stages, created_at)
               VALUES ('test-flow', 1, 'TestFlow', %s, '2026-04-20T00:00:00Z')""",
            (stages_json,),
        )

        conn.execute(
            """INSERT INTO items (id, title, type, status, priority, project_id,
                                  deployment_flow, deploy_stage,
                                  created_at, updated_at, source, frozen)
               VALUES (10, 'Release item', 'issue', 'release', 'high', 1,
                       'test-flow', 'approve-deploy',
                       '2026-01-01', '2026-01-01', 'user', 0)"""
        )
        conn.execute(
            """INSERT INTO items (id, title, type, status, priority, project_id,
                                  created_at, updated_at, source, frozen)
               VALUES (11, 'Active issue', 'issue', 'implementing', 'medium', 1,
                       '2026-01-01', '2026-01-01', 'user', 0)"""
        )
        conn.execute(
            """INSERT INTO items (id, title, type, status, priority, project_id,
                                  created_at, updated_at, source, frozen)
               VALUES (12, 'Test epic', 'epic', 'implementing', 'high', 1,
                       '2026-01-01', '2026-01-01', 'user', 0)"""
        )

        conn.execute(
            """INSERT INTO deployment_runs (id, project_id, flow, status, current_stage, created_at)
               VALUES ('run-1', 1, 'test-flow', 'executing', 'approve-deploy', '2026-01-01')"""
        )
        conn.execute(
            """INSERT INTO deployment_run_items (run_id, item_id, added_at)
               VALUES ('run-1', 10, '2026-04-20T00:00:00Z')"""
        )

        conn.execute(
            """INSERT INTO epic_tasks (epic_id, task_num, title, status)
               VALUES (12, 1, 'Task one', 'done')"""
        )

        conn.commit()
    finally:
        conn.close()


@pytest.fixture()
def mutation_db(tmp_path):
    """Create a DB with all tables needed for mutation commands.

    On Postgres ``init_test_db`` repoints ``YOKE_PG_DSN`` at a disposable
    per-test database for the fixture's lifetime, so the ``_run_client``
    subprocess (factory-routed to that DSN) reads the same seeded DB.
    """
    with init_test_db(tmp_path, apply_schema=_apply_mutation_schema) as db_path:
        _seed(db_path)
        yield {"db_path": db_path, "tmp_dir": str(tmp_path)}
