"""Shared module-level helpers for doctor_hc_meta_full test files.

Underscore prefix keeps pytest from collecting this as a test module.
Used by test_doctor_hc_meta_full.py and its split siblings.

The shared `_make_conn` schema (~110 lines) plus helper functions are
consolidated here to avoid duplication across split files. Its items
table stays inline because sibling migration tests simulate pre- and
post-column states with ALTER TABLE.
"""

from __future__ import annotations

import os
import subprocess
from datetime import datetime, timedelta, timezone

from yoke_core.engines.doctor import DoctorArgs, RecordCollector
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
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


_NOW_ISO = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _iso_days_ago(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _iso_minutes_ago(minutes: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


_MAKE_CONN_DDL = """
        CREATE TABLE items (
            id INTEGER PRIMARY KEY,
            title TEXT, type TEXT, status TEXT, priority TEXT, flow TEXT,
            rework_count INTEGER, frozen INTEGER,
            blocked INTEGER DEFAULT 0, blocked_reason TEXT,
            github_issue TEXT, deployed_to TEXT, worktree TEXT,
            merged_at TEXT, created_at TEXT, updated_at TEXT, source TEXT,
            project_id INTEGER DEFAULT 1, project_sequence INTEGER,
            deployment_flow TEXT, deploy_stage TEXT,
            spec TEXT, design_spec TEXT, technical_plan TEXT,
            worktree_plan TEXT, shepherd_log TEXT, shepherd_caveats TEXT,
            test_results TEXT, deploy_log TEXT,
            spec_updated_at TEXT, spec_updated_by TEXT,
            resolution TEXT, resolution_ref TEXT, resolution_comment TEXT
        );
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
        INSERT INTO projects (id, slug, name, default_branch, created_at, github_repo, public_item_prefix)
        VALUES (1, 'yoke', 'Yoke', 'main', '2026-01-01T00:00:00Z', 'upyoke/yoke', 'YOK');
        INSERT INTO projects (id, slug, name, default_branch, created_at, github_repo, public_item_prefix)
        VALUES (2, 'buzz', 'Buzz', 'main', '2026-01-01T00:00:00Z', 'example-org/buzz', 'BUZ');
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
            event_name TEXT, event_outcome TEXT, user_id TEXT, org_id TEXT,
            actor_id INTEGER, environment TEXT, service TEXT, project_id INTEGER,
            item_id TEXT, task_num INTEGER, agent TEXT, tool_name TEXT,
            duration_ms INTEGER, exit_code INTEGER, trace_id TEXT,
            parent_id TEXT, anomaly_flags TEXT, envelope TEXT, created_at TEXT
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
        CREATE TABLE sites (
            id TEXT PRIMARY KEY, project_id INTEGER, name TEXT, settings TEXT
        );
        CREATE TABLE environments (
            id TEXT PRIMARY KEY, site TEXT, name TEXT
        );
        CREATE TABLE epic_dispatch_chains (
            id INTEGER PRIMARY KEY, epic_id TEXT, worktree TEXT,
            worktree_path TEXT, queue TEXT, current_index INTEGER
        );
"""


def _make_conn():
    """Create a disposable Postgres DB with extensive schema for meta HC tests.

    ``YOKE_PG_DSN`` is repointed for the returned connection's lifetime. Its
    patched ``close()`` restores the prior DSN and drops the database, so the
    doctor HCs under test run against runtime's current connection contract.

    Note: this helper carries an inline ``items`` DDL because
    ``test_doctor_hc_meta_full_migration.py`` simulates pre-/post-migration
    column states with ``ALTER TABLE items ADD COLUMN db_mutation_profile``.
    Adopting the canonical relaxed shape would require a coordinated refactor of
    that test file. Documented as a residue exemption. Schema existence checks
    resolve through backend-native catalog helpers.
    """
    from yoke_core.domain import db_backend

    from runtime.api.fixtures import pg_testdb

    name = pg_testdb.create_test_database()
    new_dsn = pg_testdb.dsn_for_test_database(name)
    prior = os.environ.get(db_backend.PG_DSN_ENV)
    os.environ[db_backend.PG_DSN_ENV] = new_dsn
    conn = db_backend.connect()
    apply_fixture_ddl(conn, _MAKE_CONN_DDL)

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
    defaults = dict(file=None, fix=False, only=None, quick=False, project="yoke", db_path=None)
    defaults.update(kwargs)
    return DoctorArgs(**defaults)


def _run_hc(hc_func, conn=None, **kwargs):
    if conn is None:
        conn = _make_conn()
    rec = RecordCollector()
    hc_func(conn, _args(**kwargs), rec)
    return rec


def _result(rec, idx=0):
    return rec.results[idx]


def _results(rec):
    return {r.check_id: (r.result, r.detail) for r in rec.results}


def _completed(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


def _ensure_migration_audit_table(conn) -> None:
    """Create the final-shape migration_audit table on a test connection."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS migration_audit (
            id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
            migration_name TEXT NOT NULL,
            description TEXT,
            tables_declared TEXT NOT NULL,
            expected_deltas TEXT NOT NULL,
            pre_row_counts TEXT NOT NULL,
            post_row_counts TEXT,
            pre_fk_violations INTEGER NOT NULL DEFAULT 0,
            post_fk_violations INTEGER,
            backup_path TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'planned'
                CHECK(state IN (
                    'planned','test_copy_created','test_applied',
                    'test_verified','rehearsed','backup_created',
                    'live_applied','live_verified','completed',
                    'test_copy_failed','test_apply_failed',
                    'test_verify_failed','backup_failed',
                    'live_apply_failed','live_verify_failed'
                )),
            failure_reason TEXT,
            exception_reason TEXT,
            source_fingerprint TEXT,
            rehearsed_at TEXT,
            lease_id INTEGER,
            test_copy_path TEXT,
            baseline_verify_result TEXT,
            author_verify_result TEXT,
            session_id TEXT,
            model_name TEXT,
            project_id TEXT,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            duration_ms INTEGER
        )
    """)
