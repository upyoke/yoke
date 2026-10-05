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
from yoke_core.api.main import app, get_db_path, get_db_readonly, get_db_readwrite

from runtime.api.api_items_fixture_schema import _SCHEMA_DDL, _SEED_ITEMS


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
               (id, title, workflow_id, workflow_version_id, status, priority,
                project_id, project_sequence,
                created_at, updated_at, source, deploy_stage, deployment_flow)
               VALUES ({p}, {p}, {p},
                       (SELECT current_version_id FROM workflows WHERE id = {p}),
                       {p}, {p}, {p}, {p},
                       '2026-03-01T00:00:00Z', {p}, 'user', {p}, {p})""",
            (
                row[0],
                row[1],
                row[2],
                row[2],
                row[3],
                row[4],
                _project_id(row[5]),
                row[0],
                row[6],
                row[7],
                row[8],
            ),
        )
    _test_flow_stages = json.dumps(
        [
            {"name": "merged", "step_runner": "auto"},
            {"name": "approve-deploy", "step_runner": "human-approval"},
            {
                "name": "prod-deploy",
                "step_runner": "github-actions-workflow",
                "workflow": "deploy.yml",
            },
            {"name": "complete", "step_runner": "auto"},
        ]
    )
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
        "SELECT setval(pg_get_serial_sequence('items', 'id'), (SELECT COALESCE(MAX(id), 1) FROM items))"
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
        from yoke_core.domain.workflow_registry import converge_builtin_workflows
        from yoke_core.domain.workflow_schema import ensure_workflow_schema

        ensure_workflow_schema(conn)
        converge_builtin_workflows(conn)
        from yoke_core.domain.workflow_execution_instructions_schema import (
            ensure_workflow_execution_instructions_schema,
        )

        ensure_workflow_execution_instructions_schema(conn)
        from yoke_core.domain.auth_schema import create_auth_tables
        from yoke_core.domain.events_schema import ensure_event_schema
        from yoke_core.domain.org_schema import seed_default_org
        from yoke_core.domain.schema_init_actor_path_claim_tables import (
            create_actor_identity_tables,
        )
        from yoke_core.domain.decision_request_schema import (
            create_decision_request_tables,
        )

        create_actor_identity_tables(conn)
        create_auth_tables(conn)
        seed_default_org(conn)
        ensure_event_schema(conn)
        create_decision_request_tables(conn)
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
        with init_test_db(
            Path(tmp_dir), apply_schema=_apply_schema_and_seed
        ) as db_path:
            _ov_path, _ov_ro, _ov_rw = _install_db_overrides(db_path)
            with (
                patch.dict(os.environ, {"YOKE_DB": db_path}, clear=False),
                patch("yoke_core.api.main.get_db_path", _ov_path),
                patch("yoke_core.api.main.get_db_readonly", _ov_ro),
                patch("yoke_core.api.main.get_db_readwrite", _ov_rw),
            ):
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
