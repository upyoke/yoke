"""Shared schemas, fixtures, and helpers for the test_api_*.py suite.

Provides the ``test_db`` and ``client`` fixtures plus the ``_client_for_db``
and ``_startup_error_for_db`` helpers. Imported by ``test_api.py``,
``test_api_board.py``, and ``test_api_queue.py`` via:

    from runtime.api.test_api_helpers import test_db, client  # noqa: F401

The module name is intentionally ``test_*`` so it sits next to the test
files; it has no test_ functions, so pytest collects nothing from it.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

# Ensure the repo root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from runtime.api.auth_test_helpers import mint_api_auth_context
from yoke_core.domain import db_backend
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from runtime.api.test_dependency_schema import (
    ITEMS_SCHEMA,
    ITEM_DEPENDENCIES_SCHEMA,  # noqa: F401
    PROJECTS_SCHEMA,
)
from yoke_core.api.main import app, get_db_path, get_db_readonly, get_db_readwrite
from yoke_core.domain.strategy_docs import STRATEGY_DOCS_CREATE_TABLE_SQL


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


CAPABILITIES_SCHEMA = """
CREATE TABLE project_capabilities (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL,
    type TEXT NOT NULL,
    settings TEXT DEFAULT '{}',
    verified_at TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(project_id, type)
);
"""

DEPLOYMENT_FLOWS_SCHEMA = """
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
    status TEXT NOT NULL DEFAULT 'active',
    UNIQUE(project_id, name)
);
"""

DEPLOYMENT_RUNS_SCHEMA = """
CREATE TABLE deployment_runs (
    id TEXT PRIMARY KEY,
    project_id INTEGER NOT NULL,
    flow TEXT NOT NULL,
    target_env TEXT,
    release_lineage TEXT,
    status TEXT NOT NULL DEFAULT 'created'
      CHECK(status IN ('created','executing','succeeded','failed','cancelled')),
    current_stage TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    created_by TEXT DEFAULT 'operator'
);
"""

DEPLOYMENT_RUN_ITEMS_SCHEMA = """
CREATE TABLE deployment_run_items (
    run_id TEXT NOT NULL,
    item_id INTEGER NOT NULL,
    added_at TEXT NOT NULL,
    PRIMARY KEY (run_id, item_id)
);
"""

EPIC_TASKS_SCHEMA = """
CREATE TABLE epic_tasks (
    epic_id INTEGER NOT NULL,
    task_num INTEGER NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    body TEXT,
    dependencies TEXT,
    PRIMARY KEY (epic_id, task_num)
);
"""

QA_REQUIREMENTS_SCHEMA = """
CREATE TABLE qa_requirements (
    id INTEGER PRIMARY KEY,
    item_id INTEGER,
    epic_id INTEGER,
    task_num INTEGER,
    deployment_run_id TEXT,
    qa_kind TEXT NOT NULL,
    qa_phase TEXT NOT NULL DEFAULT 'verification',
    target_env TEXT,
    blocking_mode TEXT NOT NULL DEFAULT 'blocking',
    requirement_source TEXT NOT NULL DEFAULT 'explicit',
    success_policy TEXT NOT NULL DEFAULT 'blocking',
    capability_requirements TEXT,
    suite_id TEXT,
    waived_at TEXT,
    waiver_rationale TEXT,
    created_at TEXT NOT NULL
);
"""

QA_RUNS_SCHEMA = """
CREATE TABLE qa_runs (
    id INTEGER PRIMARY KEY,
    qa_requirement_id INTEGER NOT NULL,
    executor_type TEXT,
    verdict TEXT,
    raw_result TEXT,
    created_at TEXT NOT NULL
);
"""


def _sync_postgres_sequences(conn) -> None:
    """Advance identity sequences after explicit fixture ids."""
    conn.execute(
        "SELECT setval(pg_get_serial_sequence('items', 'id'), "
        "(SELECT COALESCE(MAX(id), 1) FROM items))"
    )


def _apply_schema_and_seed() -> None:
    """Create the test schema and seed rows in the active Postgres test DB."""
    from yoke_core.domain import db_backend

    conn = db_backend.connect()
    try:
        _apply_schema_and_seed_on_conn(conn)
        _sync_postgres_sequences(conn)
    finally:
        conn.close()


def _apply_schema_and_seed_on_conn(conn) -> None:
    """Apply this fixture's schema and seed data to a DB connection."""
    apply_fixture_ddl(
        conn,
        PROJECTS_SCHEMA
        + ITEMS_SCHEMA
        + CAPABILITIES_SCHEMA
        + DEPLOYMENT_FLOWS_SCHEMA
        + DEPLOYMENT_RUNS_SCHEMA
        + DEPLOYMENT_RUN_ITEMS_SCHEMA
        + EPIC_TASKS_SCHEMA
        + QA_REQUIREMENTS_SCHEMA
        + QA_RUNS_SCHEMA
        + STRATEGY_DOCS_CREATE_TABLE_SQL
        + ";\n",
    )

    # Seed items
    conn.execute(
        """INSERT INTO items
           (id, title, type, status, priority, project_id, project_sequence,
            created_at, updated_at, source, deploy_stage)
           VALUES (1, 'First item', 'issue', 'implementing', 'high', 1, 1,
                   '2026-03-01T00:00:00Z', '2026-03-02T00:00:00Z', 'user',
                   NULL)"""
    )
    conn.execute(
        """INSERT INTO items
           (id, title, type, status, priority, project_id, project_sequence,
            created_at, updated_at, source, deploy_stage)
           VALUES (2, 'Second item', 'epic', 'done', 'medium', 1, 2,
                   '2026-03-01T00:00:00Z', '2026-03-03T00:00:00Z', 'user', NULL)"""
    )
    conn.execute(
        """INSERT INTO items
           (id, title, type, status, priority, project_id, project_sequence,
            created_at, updated_at, source, deploy_stage)
           VALUES (3, 'Buzz item', 'issue', 'idea', 'low', 2, 3,
                   '2026-03-01T00:00:00Z', '2026-03-04T00:00:00Z', 'user', NULL)"""
    )
    # Item 4: at a human-approval stage in a flow with a deployment run
    conn.execute(
        """INSERT INTO items
           (id, title, type, status, priority, project_id, project_sequence,
            created_at, updated_at, source, deploy_stage, deployment_flow)
           VALUES (4, 'Awaiting approval', 'issue', 'release', 'high', 1, 4,
                   '2026-03-01T00:00:00Z', '2026-03-05T00:00:00Z', 'user',
                   'approve-deploy', 'test-approval-flow')"""
    )
    conn.execute(
        """INSERT INTO items
           (id, title, type, status, priority, project_id, project_sequence,
            created_at, updated_at, source, deploy_stage)
           VALUES (5, 'Cancelled item', 'issue', 'cancelled', 'low', 1, 5,
                   '2026-03-01T00:00:00Z', '2026-03-06T00:00:00Z', 'user', NULL)"""
    )

    # Seed deployment flow with a human-approval stage
    _test_flow_stages = json.dumps([
        {"name": "merged", "executor": "auto"},
        {"name": "approve-deploy", "executor": "human-approval"},
        {"name": "prod-deploy", "executor": "github-actions-workflow", "workflow": "deploy.yml"},
        {"name": "complete", "executor": "auto"},
    ])
    p = _p(conn)
    conn.execute(
        f"""INSERT INTO deployment_flows (id, project_id, name, description, stages, created_at)
           VALUES ('test-approval-flow', 1, 'TestApproval',
                   'Test flow with approval gate', {p}, '2026-04-20T00:00:00Z')""",
        (_test_flow_stages,),
    )

    # Seed deployment run for item 4
    conn.execute(
        """INSERT INTO deployment_runs
           (id, project_id, flow, status, current_stage, created_at, created_by)
           VALUES ('run-20260325-001', 1, 'test-approval-flow', 'executing',
                   'approve-deploy', '2026-03-25T00:00:00Z', 'operator')"""
    )
    conn.execute(
        """INSERT INTO deployment_run_items (run_id, item_id, added_at)
           VALUES ('run-20260325-001', 4, '2026-03-25T00:00:00Z')"""
    )

    conn.commit()


@pytest.fixture()
def test_db():
    """Fixture that creates a Postgres test DB and overrides FastAPI deps."""
    tmp_dir = tempfile.mkdtemp()
    try:
        with init_test_db(Path(tmp_dir), apply_schema=_apply_schema_and_seed) as db_path:
            with _install_overrides(db_path):
                yield {"db_path": db_path, "tmp_dir": tmp_dir}
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@pytest.fixture()
def client(test_db):
    """Return a TestClient wired to the test DB."""
    with TestClient(app) as client:
        conn = connect_test_db(test_db["db_path"])
        try:
            auth = mint_api_auth_context(conn)
        finally:
            conn.close()
        client.headers.update(auth.headers)
        yield client


@contextmanager
def _install_overrides(db_path: str):
    """Bind FastAPI dependency overrides to a backend-routed test DB."""
    def _override_db_path() -> str:
        return db_path

    def _override_db_readonly():
        return connect_test_db(db_path)

    def _override_db_readwrite():
        return connect_test_db(db_path)

    app.dependency_overrides[get_db_path] = _override_db_path
    app.dependency_overrides[get_db_readonly] = _override_db_readonly
    app.dependency_overrides[get_db_readwrite] = _override_db_readwrite

    patchers = (
        patch("yoke_core.api.main.get_db_path", _override_db_path),
        patch("yoke_core.api.main.get_db_readonly", _override_db_readonly),
        patch("yoke_core.api.main.get_db_readwrite", _override_db_readwrite),
    )
    for patcher in patchers:
        patcher.start()

    try:
        with patch.dict(os.environ, {"YOKE_DB": db_path}, clear=False):
            yield
    finally:
        app.dependency_overrides.clear()
        for patcher in reversed(patchers):
            patcher.stop()


@contextmanager
def _client_for_db(db_path: str):
    """Yield a TestClient bound to a specific temp DB path."""
    with _install_overrides(db_path):
        with TestClient(app) as client:
            conn = connect_test_db(db_path)
            try:
                auth = mint_api_auth_context(conn)
            finally:
                conn.close()
            client.headers.update(auth.headers)
            yield client


def _startup_error_for_db(db_path: str) -> str:
    """Return the startup failure message for a DB that cannot boot the API."""
    with pytest.raises(RuntimeError) as exc_info:
        with _client_for_db(db_path) as _client:
            pass  # startup should fail before the client is yielded
    return str(exc_info.value)
