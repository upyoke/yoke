"""Shared module-level helpers for doctor_hc_git_full test files.

Underscore prefix keeps pytest from collecting this as a test module.
Used by test_doctor_hc_git_full.py and its split siblings.

Non-fixture helpers — plain Python functions invoked directly. Schema
duplication across split files would risk drift; consolidating here keeps
the test surfaces self-contained while the schema lives in one place.
"""

from __future__ import annotations

import subprocess
import textwrap

from yoke_core.engines.doctor import DoctorArgs, RecordCollector
from yoke_core.engines._project_identity_test_helpers import (
    _insert_deployment_flow,
    _insert_item,
    _project_id,
    _seed_project,
)
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl


def _default_args(**overrides) -> DoctorArgs:
    defaults = dict(only=None, quick=False, file=None, fix=False, project="yoke")
    defaults.update(overrides)
    return DoctorArgs(**defaults)


def _make_conn():
    """Create a disposable Postgres DB with minimal schema for git/GitHub HC testing.

    The backing database is dropped when the connection closes; a
    garbage-collection finalizer covers connections a test never closes.
    """
    from runtime.api.fixtures import pg_testdb

    name = pg_testdb.create_test_database()
    conn = pg_testdb.connect_test_database(name)
    apply_fixture_ddl(conn, textwrap.dedent("""\
        CREATE TABLE items (
            id INTEGER PRIMARY KEY,
            title TEXT, type TEXT, status TEXT, priority TEXT,
            project_id INTEGER DEFAULT 1, project_sequence INTEGER,
            github_issue TEXT, flow TEXT, rework_count INTEGER,
            deployed_to TEXT, updated_at TEXT, worktree TEXT,
            deployment_flow TEXT, merged_at TEXT,
            deploy_stage TEXT, created_at TEXT
        );
        CREATE TABLE epic_tasks (
            epic_id TEXT, task_num INTEGER, title TEXT,
            status TEXT, last_heartbeat TEXT,
            dispatch_attempts INTEGER DEFAULT 0,
            worktree TEXT, github_issue TEXT,
            PRIMARY KEY (epic_id, task_num)
        );
        CREATE TABLE projects (
            id INTEGER PRIMARY KEY, slug TEXT UNIQUE, name TEXT,
            default_branch TEXT, created_at TEXT,
            github_repo TEXT, public_item_prefix TEXT DEFAULT 'YOK'
        );
        INSERT INTO projects
            (id, slug, name, default_branch, created_at,
             github_repo, public_item_prefix)
        VALUES
            (1, 'yoke', 'Yoke', 'main',
             '2026-01-01T00:00:00Z', 'upyoke/yoke', 'YOK');
        CREATE TABLE ouroboros_entries (
            id INTEGER PRIMARY KEY, agent TEXT, context TEXT,
            category TEXT, body TEXT, created_at TEXT,
            reviewed_at TEXT, archived_at TEXT
        );
        CREATE TABLE events (
            id INTEGER PRIMARY KEY, event_id TEXT, source_type TEXT,
            event_name TEXT, event_type TEXT, item_id TEXT,
            task_num INTEGER, envelope TEXT, created_at TEXT
        );
        CREATE TABLE epic_dispatch_chains (
            id INTEGER PRIMARY KEY, epic_id TEXT, worktree TEXT,
            worktree_path TEXT, queue TEXT, current_index INTEGER
        );
        CREATE TABLE sites (
            id TEXT PRIMARY KEY, project_id INTEGER, name TEXT
        );
        CREATE TABLE environments (
            id TEXT PRIMARY KEY, site TEXT, name TEXT
        );
        CREATE TABLE deployment_flows (
            id TEXT PRIMARY KEY, project_id INTEGER, stages TEXT
        );
    """))
    return pg_testdb.drop_database_on_close(conn, name)


def _run_hc(hc_func, conn=None, **kwargs):
    """Run a single HC and return the RecordCollector."""
    if conn is None:
        conn = _make_conn()
    args = _default_args(**kwargs)
    rec = RecordCollector()
    hc_func(conn, args, rec)
    return rec


def _result(rec: RecordCollector, idx: int = 0):
    return rec.results[idx]


def _completed(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess([], returncode, stdout, stderr)
