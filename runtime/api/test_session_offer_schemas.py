"""Shared schemas + DB seeding helper for session-offer/session-end API tests.

The split test_api_sessions[_*].py files all build a temporary DB with the same
session/claim/event tables and the same seed items. Centralized here so the
splits stay self-contained without copying ~150 lines of DDL.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from yoke_core.domain import db_backend
from runtime.api.auth_test_helpers import mint_api_auth_context
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from runtime.api.sessions_api_stale_test_helpers import apply_ddl_statements
from runtime.api.test_dependency_schema import (
    ITEMS_SCHEMA,
    ITEM_DEPENDENCIES_SCHEMA,
    PROJECTS_SCHEMA,
)
from yoke_core.domain.work_claim_target_sql import TARGET_KIND_CHECK_SQL
from yoke_core.api.main import (
    app,
    get_config_path,
    get_db_path,
    get_db_readonly,
    get_db_readwrite,
)


def fresh_now() -> str:
    """Return a fresh wall-clock timestamp to keep session heartbeats non-stale."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


ACTIVE_SESSIONS_SCHEMA = """
CREATE TABLE harness_sessions (
    session_id TEXT PRIMARY KEY,
    executor TEXT NOT NULL,
    executor_surface TEXT DEFAULT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    execution_lane TEXT NOT NULL DEFAULT 'DARIUS',
    executor_version TEXT, machine_id TEXT,
    workspace TEXT NOT NULL,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    mode TEXT DEFAULT 'wait',
    offered_at TEXT NOT NULL,
    last_heartbeat TEXT NOT NULL,
    ended_at TEXT,
    offer_envelope TEXT,
    current_item_id TEXT DEFAULT NULL,
    current_item_set_at TEXT DEFAULT NULL,
    recent_item_id TEXT DEFAULT NULL,
    recent_item_status TEXT DEFAULT NULL,
    recent_item_recorded_at TEXT DEFAULT NULL,
    actor_id INTEGER DEFAULT NULL,
    last_tool_call_at TEXT DEFAULT NULL,
    tool_call_count INTEGER NOT NULL DEFAULT 0,
    episode_started_at TEXT DEFAULT NULL,
    pending_resume_notice TEXT DEFAULT NULL
);
"""

WORK_CLAIMS_SCHEMA = f"""
CREATE TABLE work_claims (
    id INTEGER PRIMARY KEY,
    session_id TEXT NOT NULL,
    target_kind TEXT NOT NULL CHECK({TARGET_KIND_CHECK_SQL}),
    scope TEXT NOT NULL,
    claim_type TEXT NOT NULL DEFAULT 'exclusive' CHECK(claim_type='exclusive'),
    claimed_at TEXT NOT NULL,
    last_heartbeat TEXT NOT NULL,
    released_at TEXT,
    release_reason TEXT CHECK(release_reason IS NULL OR release_reason IN ('completed','released','reclaimed','handed_off','expired','session_ended')),
    reason TEXT,
    reason_intent TEXT,
    release_reason_intent TEXT,
    FOREIGN KEY (session_id) REFERENCES harness_sessions(session_id)
);
"""

# Empty ``actors`` table so the registration path's explicit-actor check
# (``validate_actor_id``) issues a clean ``SELECT 1 FROM actors`` that returns
# no rows rather than hitting a missing relation — a missing-relation error
# would poison the transaction, so the table must exist (empty -> resolver
# returns ``None``) before the session INSERT runs in the same txn.
ACTORS_SCHEMA = """
CREATE TABLE actors (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL DEFAULT 'system',
    system_component TEXT,
    created_at TEXT
);
"""

EVENTS_SCHEMA = """
CREATE TABLE events (
    id INTEGER PRIMARY KEY,
    event_id TEXT UNIQUE,
    event_name TEXT NOT NULL,
    event_kind TEXT,
    event_type TEXT,
    source_type TEXT,
    session_id TEXT,
    severity TEXT DEFAULT 'INFO',
    event_outcome TEXT,
    org_id TEXT,
    environment TEXT,
    service TEXT,
    project_id INTEGER DEFAULT 1 REFERENCES projects(id),
    actor_id INTEGER,
    item_id TEXT,
    task_num INTEGER,
    agent TEXT,
    tool_name TEXT,
    duration_ms INTEGER,
    exit_code INTEGER,
    trace_id TEXT,
    anomaly_flags TEXT,
    tool_use_id TEXT,
    turn_id TEXT,
    hook_event_name TEXT,
    envelope TEXT,
    created_at TEXT NOT NULL
);
"""


def _apply_session_offer_schema() -> None:
    """``init_test_db`` schema applier: session tables + seed items for offer tests.

    Resolves its connection through the backend factory (the repointed
    per-test DSN) so the bespoke DDL + seed lands in the disposable DB.
    """
    conn = db_backend.connect()
    try:
        apply_ddl_statements(
            conn,
            PROJECTS_SCHEMA,
            ITEMS_SCHEMA,
            ACTIVE_SESSIONS_SCHEMA,
            WORK_CLAIMS_SCHEMA,
            EVENTS_SCHEMA,
            ITEM_DEPENDENCIES_SCHEMA,
            ACTORS_SCHEMA,
        )
        from yoke_core.domain.workflow_registry import converge_builtin_workflows
        from yoke_core.domain.workflow_schema import ensure_workflow_schema

        ensure_workflow_schema(conn)
        converge_builtin_workflows(conn)

        # Seed items: one runnable issue, one done (terminal), one blocked
        conn.execute(
            """INSERT INTO items
               (id, title, workflow_id, workflow_version_id, status, priority, project_id, project_sequence,
                created_at, updated_at, source, frozen)
               VALUES (10, 'Runnable task', 'issue', (SELECT current_version_id FROM workflows WHERE id='issue'), 'refined-idea', 'high', 1, 10,
                       '2026-03-01T00:00:00Z', '2026-03-02T00:00:00Z', 'user', 0)"""
        )
        conn.execute(
            """INSERT INTO items
               (id, title, workflow_id, workflow_version_id, status, priority, project_id, project_sequence,
                created_at, updated_at, source, frozen)
               VALUES (11, 'Done task', 'issue', (SELECT current_version_id FROM workflows WHERE id='issue'), 'done', 'medium', 1, 11,
                       '2026-03-01T00:00:00Z', '2026-03-03T00:00:00Z', 'user', 0)"""
        )
        conn.execute(
            """INSERT INTO items
               (id, title, workflow_id, workflow_version_id, status, priority, project_id, project_sequence,
                created_at, updated_at, source, frozen)
               VALUES (12, 'Blocked task', 'issue', (SELECT current_version_id FROM workflows WHERE id='issue'), 'idea', 'low', 1, 12,
                       '2026-03-01T00:00:00Z', '2026-03-04T00:00:00Z', 'user', 0)"""
        )
        # Hard-block: child is blocked by parent (which is not terminal)
        conn.execute(
            """INSERT INTO item_dependencies
               (dependent_item_id, blocking_item_id, gate_point, satisfaction, source, rationale, created_at)
               VALUES (12, 10, 'activation', 'status:done', 'shepherd', 'YOK-12 depends on YOK-10', '2026-03-01T00:00:00Z')"""
        )
        from yoke_core.domain.workflow_registry import resolve_current_workflow_pin

        workflow_id, workflow_version_id = resolve_current_workflow_pin(
            conn,
            "issue",
        )
        conn.execute(
            "UPDATE items SET workflow_id = %s, workflow_version_id = %s",
            (workflow_id, workflow_version_id),
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture()
def session_offer_db(tmp_path, monkeypatch):
    """Fixture for session-offer tests with session/claim tables.

    Local to each importing test file via ``pytest_plugins = []`` etc. is not
    needed — pytest auto-discovers fixtures defined here when the helper is
    imported in a test file. Each test file re-exports this fixture via
    ``from .test_session_offer_schemas import session_offer_db``.

    Disposable per-test Postgres DB via ``init_test_db``, with ``YOKE_PG_DSN``
    repointed for the context's lifetime. The ``with`` stays open across the
    yield so the FastAPI dependency overrides — routed through
    ``connect_test_db`` — and the test body's reads all share this DB; read
    paths use the same factory connection (no separate read-only mode).
    """
    tmp_dir = str(tmp_path / "workspace")
    os.makedirs(tmp_dir, exist_ok=True)

    with init_test_db(tmp_path, apply_schema=_apply_session_offer_schema) as db_path:
        auth_conn = connect_test_db(db_path)
        try:
            auth = mint_api_auth_context(auth_conn)
        finally:
            auth_conn.close()

        def _override_db_path() -> str:
            return db_path

        def _override_config_path():
            from yoke_core.api.routing_config import config_path_from_db_path

            return config_path_from_db_path(db_path)

        def _override_db_readonly():
            return connect_test_db(db_path)

        def _override_db_readwrite():
            return connect_test_db(db_path)

        app.dependency_overrides[get_db_path] = _override_db_path
        app.dependency_overrides[get_config_path] = _override_config_path
        app.dependency_overrides[get_db_readonly] = _override_db_readonly
        app.dependency_overrides[get_db_readwrite] = _override_db_readwrite

        with (
            patch("yoke_core.api.main.get_db_path", _override_db_path),
            patch("yoke_core.api.main.get_config_path", _override_config_path),
            patch("yoke_core.api.main.get_db_readonly", _override_db_readonly),
            patch("yoke_core.api.main.get_db_readwrite", _override_db_readwrite),
        ):
            from runtime.api.test_service_client_sessions_helpers import (
                _map_offer_workspace_home,
            )

            _map_offer_workspace_home(monkeypatch, tmp_dir)
            yield {
                "db_path": db_path,
                "tmp_dir": tmp_dir,
                "auth_headers": auth.headers,
            }

        app.dependency_overrides.clear()
