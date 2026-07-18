"""Shared module-level helpers for doctor_meta test files.

Underscore prefix keeps pytest from collecting this as a test module.
Used by test_doctor_meta.py and its split siblings (project, lifecycle).

This is a non-fixture helper module — it exposes plain Python functions
that callers invoke directly. The shared `_make_conn` schema is large
enough (~120 lines) that duplicating it across each split file would
risk drift; consolidating here keeps the test surfaces self-contained
while the schema definition lives in one place.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from yoke_core.engines.doctor import DoctorArgs, RecordCollector
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from runtime.api.fixtures.schema_ddl_items import _ITEMS_RELAXED_DDL
from yoke_core.engines._project_identity_test_helpers import (
    _insert_deployment_flow,
    _insert_item,
    _project_id,
    _seed_project,
)


def _p(conn) -> str:
    """Parameter marker for the active test connection."""
    from yoke_core.domain import db_backend

    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _iso_offset(**kwargs) -> str:
    """Return a UTC timestamp offset from now."""
    return (datetime.now(timezone.utc) + timedelta(**kwargs)).strftime("%Y-%m-%d %H:%M:%S")


_REST_DDL = """
        CREATE TABLE epic_tasks (
            id INTEGER PRIMARY KEY,
            epic_id INTEGER, task_num INTEGER, title TEXT,
            worktree TEXT, context_estimate TEXT, dependencies TEXT,
            status TEXT, dispatch_attempts INTEGER, body TEXT,
            github_issue TEXT, branch TEXT, worktree_path TEXT,
            blocked_by TEXT, max_attempts INTEGER, agent_id TEXT,
            last_heartbeat TEXT
        );

        CREATE TABLE shepherd_verdicts (
            id INTEGER PRIMARY KEY,
            item TEXT, transition TEXT, worker TEXT, verdict TEXT,
            caveats TEXT, attempt INTEGER, created_at TEXT
        );

        CREATE TABLE deployment_flows (
            id TEXT PRIMARY KEY, project_id INTEGER, name TEXT, description TEXT,
            stages TEXT, on_failure TEXT, created_at TEXT,
            target_env TEXT, done_description TEXT
        );

        CREATE TABLE deployment_runs (
            id TEXT PRIMARY KEY, project_id INTEGER, flow TEXT, target_env TEXT,
            release_lineage TEXT, status TEXT, current_stage TEXT,
            created_at TEXT, started_at TEXT, completed_at TEXT, created_by TEXT
        );

        CREATE TABLE deployment_run_items (
            run_id TEXT, item_id INTEGER, added_at TEXT,
            PRIMARY KEY (run_id, item_id)
        );

        CREATE TABLE projects (
            id INTEGER PRIMARY KEY, slug TEXT UNIQUE, name TEXT,
            default_branch TEXT, created_at TEXT,
            emoji TEXT, github_repo TEXT, public_item_prefix TEXT DEFAULT 'YOK'
        );
        INSERT INTO projects
            (id, slug, name, default_branch, created_at,
             github_repo, public_item_prefix)
        VALUES
            (1, 'yoke', 'Yoke', 'main',
             '2026-01-01T00:00:00Z', 'upyoke/yoke', 'YOK');
        INSERT INTO projects
            (id, slug, name, default_branch, created_at,
             github_repo, public_item_prefix)
        VALUES
            (2, 'externalwebapp', 'ExternalWebapp', 'main',
             '2026-01-01T00:00:00Z', 'example-org/externalwebapp', 'EXT');

        CREATE TABLE project_capabilities (
            id INTEGER PRIMARY KEY, project_id INTEGER, type TEXT, config TEXT,
            verified_at TEXT, created_at TEXT, settings TEXT
        );

        CREATE TABLE ephemeral_environments (
            id INTEGER PRIMARY KEY, project_id INTEGER, branch TEXT, item TEXT,
            workflow_run_id TEXT, github_ref TEXT, port_api INTEGER,
            port_web INTEGER, url TEXT, status TEXT, started_at TEXT,
            stopped_at TEXT, health_check_url TEXT, deployed_sha TEXT,
            created_at TEXT
        );

        CREATE TABLE qa_requirements (
            id INTEGER PRIMARY KEY, item_id INTEGER, epic_id INTEGER,
            task_num INTEGER, deployment_run_id TEXT, qa_kind TEXT,
            qa_phase TEXT, target_env TEXT, blocking_mode TEXT,
            requirement_source TEXT, success_policy TEXT,
            capability_requirements TEXT, suite_id TEXT,
            waived_at TEXT, waiver_rationale TEXT, created_at TEXT,
            waiver_source TEXT
        );

        CREATE TABLE qa_runs (
            id INTEGER PRIMARY KEY, qa_requirement_id INTEGER,
            executor_type TEXT, qa_kind TEXT, verdict TEXT,
            score REAL, confidence REAL, raw_result TEXT,
            duration_ms INTEGER, started_at TEXT, completed_at TEXT,
            created_at TEXT
        );

        CREATE TABLE events (
            id INTEGER PRIMARY KEY, event_id TEXT, source_type TEXT,
            session_id TEXT, severity TEXT, event_kind TEXT, event_type TEXT,
            event_name TEXT, event_outcome TEXT, org_id TEXT,
            actor_id INTEGER, environment TEXT, service TEXT, project_id INTEGER,
            item_id TEXT, task_num INTEGER, agent TEXT, tool_name TEXT,
            duration_ms INTEGER, exit_code INTEGER, trace_id TEXT,
            parent_id TEXT, anomaly_flags TEXT, envelope TEXT, created_at TEXT
        );

        CREATE TABLE item_status_transitions (
            id INTEGER PRIMARY KEY, item_id INTEGER NOT NULL,
            task_num INTEGER, from_status TEXT, to_status TEXT NOT NULL,
            source TEXT, session_id TEXT, actor_id INTEGER,
            project_id INTEGER,
            created_at TEXT NOT NULL DEFAULT '2026-01-01T00:00:00Z'
        );

        CREATE TABLE event_registry (
            event_name TEXT PRIMARY KEY, event_kind TEXT, event_type TEXT,
            owner_service TEXT, description TEXT, context_schema TEXT,
            severity_default TEXT, added_in TEXT, status TEXT
        );

        CREATE TABLE ouroboros_entries (
            id INTEGER PRIMARY KEY, timestamp TEXT, agent TEXT,
            context TEXT, category TEXT, body TEXT,
            reviewed_at TEXT, archived_at TEXT, created_at TEXT,
            project_id INTEGER
        );

        CREATE TABLE item_dependencies (
            id INTEGER PRIMARY KEY, dependent_item TEXT, blocking_item TEXT,
            gate_point TEXT, satisfaction TEXT, source TEXT, session_id INTEGER,
            rationale TEXT, evidence_json TEXT, created_at TEXT
        );
"""


def _make_conn():
    """Create a disposable Postgres DB for doctor_meta HC testing.

    ``YOKE_PG_DSN`` is repointed for the returned connection's lifetime. Its
    patched ``close()`` restores the prior DSN and drops the database, so the
    doctor HCs under test run against runtime's current connection contract.

    The ``items`` table uses the relaxed-shape derivation from
    :mod:`runtime.api.fixtures.schema_ddl_items` so future column additions in
    canonical schema init flow through automatically. Schema existence checks
    resolve through backend-native catalog helpers.
    """
    from yoke_core.domain import db_backend

    from runtime.api.fixtures import pg_testdb

    name = pg_testdb.create_test_database()
    new_dsn = pg_testdb.dsn_for_test_database(name)
    prior = os.environ.get(db_backend.PG_DSN_ENV)
    os.environ[db_backend.PG_DSN_ENV] = new_dsn
    conn = db_backend.connect()
    apply_fixture_ddl(conn, _ITEMS_RELAXED_DDL)
    apply_fixture_ddl(conn, _REST_DDL)

    _base_close = conn.close

    def _close_and_drop():
        _base_close()
        if prior is not None:
            os.environ[db_backend.PG_DSN_ENV] = prior
        else:
            os.environ.pop(db_backend.PG_DSN_ENV, None)
        pg_testdb.drop_test_database(name)

    conn.close = _close_and_drop
    return conn


def _args(**kwargs) -> DoctorArgs:
    """Create DoctorArgs with defaults for testing."""
    defaults = dict(file=None, fix=False, only=None, quick=False, project="yoke", db_path=None)
    defaults.update(kwargs)
    return DoctorArgs(**defaults)


def _results(rec: RecordCollector) -> dict:
    """Return a dict of check_id -> (result, detail) from the collector."""
    return {r.check_id: (r.result, r.detail) for r in rec.results}
