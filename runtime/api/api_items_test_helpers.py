"""Shared schema, seed data, and test-client builders for ``test_api_items_*``.

Filename omits the ``test_`` prefix so pytest does not collect it. Split files
import ``_startup_test_db``, ``_client_for_db``, ``_startup_error_for_db``, and
``make_test_db_fixture`` and wrap them in local ``@pytest.fixture`` shims. The
normal fixture builds one seeded Postgres test DB and points both FastAPI
dependency overrides and function-call dispatch at it. Startup-gate tests use
the same Postgres fixture seam, then seed legacy status rows before the
TestClient lifespan starts.
"""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from runtime.api.auth_test_helpers import mint_api_auth_context
from yoke_core.domain import db_backend
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from runtime.api.test_dependency_schema import ITEMS_SCHEMA, PROJECTS_SCHEMA
from yoke_core.api.main import app, get_db_path, get_db_readonly, get_db_readwrite

# Shared schema: ITEMS_SCHEMA (imported) + the family tables the API tests need.
# item_sections backs the section / progress-log writes; harness_sessions backs
# the dispatcher's actor-identity binding (queried on every mutating call).
_SCHEMA_DDL = PROJECTS_SCHEMA + ITEMS_SCHEMA + """
CREATE TABLE project_capabilities (
    id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL, type TEXT NOT NULL,
    settings TEXT DEFAULT '{}', verified_at TEXT, created_at TEXT NOT NULL,
    UNIQUE(project_id, type)
);
CREATE TABLE strategy_docs (
    id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL,
    slug TEXT NOT NULL, content TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL,
    updated_by_actor_id INTEGER, archived_at TEXT, UNIQUE(project_id, slug)
);
CREATE TABLE deployment_flows (
    id TEXT PRIMARY KEY, project_id INTEGER NOT NULL, name TEXT NOT NULL,
    description TEXT, stages TEXT NOT NULL, on_failure TEXT DEFAULT 'halt',
    created_at TEXT NOT NULL, target_env TEXT DEFAULT NULL,
    done_description TEXT DEFAULT NULL,
    status TEXT NOT NULL DEFAULT 'active', UNIQUE(project_id, name)
);
CREATE TABLE deployment_runs (
    id TEXT PRIMARY KEY, project_id INTEGER NOT NULL, flow TEXT NOT NULL,
    target_env TEXT, release_lineage TEXT,
    status TEXT NOT NULL DEFAULT 'created'
      CHECK(status IN ('created','executing','succeeded','failed','cancelled')),
    current_stage TEXT, created_at TEXT NOT NULL, started_at TEXT,
    completed_at TEXT, created_by TEXT DEFAULT 'operator'
);
CREATE TABLE deployment_run_items (
    run_id TEXT NOT NULL, item_id INTEGER NOT NULL, added_at TEXT NOT NULL,
    PRIMARY KEY (run_id, item_id)
);
CREATE TABLE epic_tasks (
    epic_id INTEGER NOT NULL, task_num INTEGER NOT NULL, title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending', body TEXT, dependencies TEXT,
    PRIMARY KEY (epic_id, task_num)
);
CREATE TABLE qa_requirements (
    id INTEGER PRIMARY KEY, item_id INTEGER, epic_id INTEGER, task_num INTEGER,
    deployment_run_id TEXT, qa_kind TEXT NOT NULL,
    qa_phase TEXT NOT NULL DEFAULT 'verification', target_env TEXT,
    blocking_mode TEXT NOT NULL DEFAULT 'blocking',
    requirement_source TEXT NOT NULL DEFAULT 'explicit',
    success_policy TEXT NOT NULL DEFAULT 'blocking', capability_requirements TEXT,
    suite_id TEXT, waived_at TEXT, waiver_rationale TEXT, created_at TEXT NOT NULL
);
CREATE TABLE qa_runs (
    id INTEGER PRIMARY KEY, qa_requirement_id INTEGER NOT NULL,
    executor_type TEXT, verdict TEXT, raw_result TEXT, created_at TEXT NOT NULL
);
CREATE TABLE item_sections (
    item_id INTEGER, section_name TEXT, content TEXT, ordering INTEGER,
    source TEXT DEFAULT 'operator', created_at TEXT, updated_at TEXT,
    PRIMARY KEY(item_id, section_name)
);
CREATE TABLE harness_sessions (
    session_id TEXT PRIMARY KEY, actor_id INTEGER,
    project_id INTEGER NOT NULL DEFAULT 1,
    executor TEXT, executor_display_name TEXT, provider TEXT, model TEXT,
    execution_lane TEXT, capabilities TEXT, workspace TEXT, mode TEXT,
    offered_at TEXT, last_heartbeat TEXT, ended_at TEXT, offer_envelope TEXT,
    current_item_id TEXT, current_item_set_at TEXT,
    recent_item_id TEXT, recent_item_status TEXT, recent_item_recorded_at TEXT,
    last_seen_main_sha TEXT, last_drift_check_at TEXT
);
CREATE TABLE work_claims (
    id INTEGER PRIMARY KEY,
    session_id TEXT NOT NULL,
    target_kind TEXT NOT NULL CHECK(target_kind IN ('item','epic_task','process')),
    item_id INTEGER,
    epic_id INTEGER,
    task_num INTEGER,
    process_key TEXT,
    conflict_group TEXT,
    claim_type TEXT NOT NULL DEFAULT 'exclusive' CHECK(claim_type='exclusive'),
    claimed_at TEXT NOT NULL,
    last_heartbeat TEXT NOT NULL,
    released_at TEXT,
    release_reason TEXT
);
"""


# (id, title, type, status, priority, project_slug, updated_at, deploy_stage,
#  deployment_flow). Item 4 sits at a human-approval stage in a flow with a run.
_SEED_ITEMS = (
    (1, "First item", "issue", "implementing", "high", "yoke",
     "2026-03-02T00:00:00Z", None, None),
    (2, "Second item", "epic", "done", "medium", "yoke",
     "2026-03-03T00:00:00Z", None, None),
    (3, "ExternalWebapp item", "issue", "idea", "low", "externalwebapp",
     "2026-03-04T00:00:00Z", None, None),
    (4, "Awaiting approval", "issue", "release", "high", "yoke",
     "2026-03-05T00:00:00Z", "approve-deploy", "test-approval-flow"),
    (5, "Cancelled item", "issue", "cancelled", "low", "yoke",
     "2026-03-06T00:00:00Z", None, None),
)


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _project_id(slug: str) -> int:
    return 2 if slug == "externalwebapp" else 1


def _seed_rows(conn) -> None:
    """Insert the shared seed rows (5 items + approval flow + run)."""
    p = _p(conn)
    for row in _SEED_ITEMS:
        conn.execute(
            f"""INSERT INTO items
               (id, title, type, status, priority, project_id, project_sequence,
                created_at, updated_at, source, deploy_stage, deployment_flow)
               VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p},
                       '2026-03-01T00:00:00Z', {p}, 'user', {p}, {p})""",
            (row[0], row[1], row[2], row[3], row[4], _project_id(row[5]),
             row[0], row[6], row[7], row[8]),
        )
    _test_flow_stages = json.dumps([
        {"name": "merged", "executor": "auto"},
        {"name": "approve-deploy", "executor": "human-approval"},
        {"name": "prod-deploy", "executor": "github-actions-workflow", "workflow": "deploy.yml"},
        {"name": "complete", "executor": "auto"},
    ])
    conn.execute(
        f"""INSERT INTO deployment_flows (id, project_id, name, description, stages, created_at)
           VALUES ('test-approval-flow', 1, 'TestApproval',
                   'Test flow with approval gate', {p}, '2026-04-20T00:00:00Z')""",
        (_test_flow_stages,),
    )
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


def _sync_postgres_sequences(conn) -> None:
    """Advance identity sequences after explicit fixture ids."""
    conn.execute(
        "SELECT setval(pg_get_serial_sequence('items', 'id'), "
        "(SELECT COALESCE(MAX(id), 1) FROM items))"
    )


def _apply_schema_and_seed() -> None:
    """Zero-arg ``apply_schema`` strategy for :func:`init_test_db`.

    Builds the shared schema + seed against the repointed ``YOKE_PG_DSN`` and
    applies fixture DDL through the native fixture helper.
    """
    from yoke_core.domain import db_backend

    conn = db_backend.connect()
    try:
        apply_fixture_ddl(conn, _SCHEMA_DDL)
        _seed_rows(conn)
        _sync_postgres_sequences(conn)
        conn.commit()
    finally:
        conn.close()


@contextmanager
def _startup_test_db(tmp_path: Path):
    """Yield a seeded Postgres test DB for explicit startup-gate tests."""
    with init_test_db(tmp_path, apply_schema=_apply_schema_and_seed) as db_path:
        yield db_path


def _db_override_fns(db_path: str):
    """Return the (path, readonly, readwrite) FastAPI dep overrides for a DB."""
    def _path() -> str:
        return db_path

    def _readonly():
        return connect_test_db(db_path)

    def _readwrite():
        return connect_test_db(db_path)

    return _path, _readonly, _readwrite


def _install_db_overrides(db_path: str):
    """Bind the dep overrides on ``app`` and return the three fns for patching."""
    fns = _db_override_fns(db_path)
    app.dependency_overrides[get_db_path] = fns[0]
    app.dependency_overrides[get_db_readonly] = fns[1]
    app.dependency_overrides[get_db_readwrite] = fns[2]
    return fns


@contextmanager
def _client_for_db(db_path: str):
    """Yield a TestClient bound to a specific temp DB path."""
    _override_db_path, _override_db_readonly, _override_db_readwrite = (
        _install_db_overrides(db_path)
    )
    patchers = (
        patch("yoke_core.api.main.get_db_path", _override_db_path),
        patch("yoke_core.api.main.get_db_readonly", _override_db_readonly),
        patch("yoke_core.api.main.get_db_readwrite", _override_db_readwrite),
    )
    for patcher in patchers:
        patcher.start()

    try:
        with TestClient(app) as client:
            conn = connect_test_db(db_path)
            try:
                auth = mint_api_auth_context(conn)
            finally:
                conn.close()
            client.headers.update(auth.headers)
            yield client
    finally:
        app.dependency_overrides.clear()
        for patcher in reversed(patchers):
            patcher.stop()


def _startup_error_for_db(db_path: str) -> str:
    """Return the startup failure message for a DB that cannot boot the API."""
    with pytest.raises(RuntimeError) as exc_info:
        with _client_for_db(db_path) as _client:
            pass  # startup should fail before the client is yielded
    return str(exc_info.value)


def make_test_db_fixture():
    """Yield a {'db_path', 'tmp_dir'} dict with FastAPI deps overridden.

    ``db_path`` is a path token for the backend-routed test DB. The same
    seeded Postgres database backs FastAPI dependency overrides and the
    dispatched function-call handlers.
    """
    tmp_dir = tempfile.mkdtemp()
    try:
        with init_test_db(Path(tmp_dir), apply_schema=_apply_schema_and_seed) as db_path:
            _ov_path, _ov_ro, _ov_rw = _install_db_overrides(db_path)
            with patch.dict(os.environ, {"YOKE_DB": db_path}, clear=False), \
                 patch("yoke_core.api.main.get_db_path", _ov_path), \
                 patch("yoke_core.api.main.get_db_readonly", _ov_ro), \
                 patch("yoke_core.api.main.get_db_readwrite", _ov_rw):
                yield {"db_path": db_path, "tmp_dir": tmp_dir}
    finally:
        app.dependency_overrides.clear()
        import shutil

        shutil.rmtree(tmp_dir, ignore_errors=True)


def make_client_fixture():
    """Yield a TestClient bound to ``app`` (assumes deps already overridden)."""
    with TestClient(app) as client:
        conn = db_backend.connect()
        try:
            auth = mint_api_auth_context(conn)
        finally:
            conn.close()
        client.headers.update(auth.headers)
        yield client
