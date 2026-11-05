# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from runtime.api.engines.doctor_git_github_test_support import _make_completed as _make_completed

import textwrap

from pathlib import Path

from unittest.mock import patch

from runtime.api.fixtures import pg_testdb

from runtime.api.fixtures.backlog import insert_item_worktree

from runtime.api.fixtures.schema_ddl import apply_fixture_ddl

from yoke_core.engines.doctor import (
    DoctorArgs,
    RecordCollector,
    hc_epic_task_worktree_backfill,
    hc_path_confabulation,
    hc_worktree_health,
)


def _make_conn():
    """Disposable Postgres DB with minimal schema for git/file HC testing."""
    name = pg_testdb.create_test_database()
    conn = pg_testdb.drop_database_on_close(pg_testdb.connect_test_database(name), name)
    apply_fixture_ddl(
        conn,
        textwrap.dedent("""\
        CREATE TABLE items (
            id INTEGER PRIMARY KEY,
            title TEXT,
            workflow_id TEXT,
            workflow_version_id INTEGER,
            status TEXT,
            priority TEXT,
            project_id INTEGER DEFAULT 1,
            project_sequence INTEGER,
            github_issue TEXT,
            deployed_to TEXT,
            updated_at TIMESTAMPTZ,
            deployment_flow TEXT
        );
        CREATE TABLE item_worktrees (
            id INTEGER PRIMARY KEY, item_id INTEGER NOT NULL,
            branch TEXT NOT NULL, path TEXT, commit_sha TEXT,
            lane_role TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'active', created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL, released_at TIMESTAMPTZ
        );

        CREATE TABLE epic_tasks (
            epic_id INTEGER,
            task_num INTEGER,
            title TEXT,
            status TEXT,
            last_heartbeat TIMESTAMPTZ,
            dispatch_attempts INTEGER DEFAULT 0,
            item_worktree_id INTEGER,
            github_issue TEXT,
            PRIMARY KEY (epic_id, task_num)
        );

        CREATE TABLE projects (
            id INTEGER PRIMARY KEY,
            slug TEXT UNIQUE,
            name TEXT,
            default_branch TEXT,
            created_at TIMESTAMPTZ,
            github_repo TEXT,
            public_item_prefix TEXT DEFAULT 'YOK'
        );
        INSERT INTO projects
            (id, slug, name, default_branch, created_at,
             github_repo, public_item_prefix)
        VALUES
            (1, 'yoke', 'Yoke', 'main',
             '2026-01-01T00:00:00Z', 'upyoke/yoke', 'YOK');

        CREATE TABLE ouroboros_entries (
            id INTEGER PRIMARY KEY,
            agent TEXT,
            context TEXT,
            category TEXT,
            body TEXT,
            created_at TIMESTAMPTZ,
            reviewed_at TIMESTAMPTZ,
            archived_at TIMESTAMPTZ
        );

        CREATE TABLE harness_sessions (
            session_id TEXT PRIMARY KEY,
            ended_at TIMESTAMPTZ
        );
        INSERT INTO harness_sessions (session_id, ended_at)
        VALUES ('past', '2026-01-01T00:00:00Z');

        CREATE TABLE work_claims (
            id INTEGER PRIMARY KEY,
            session_id TEXT,
            target_kind TEXT,
            scope TEXT NOT NULL,
            released_at TIMESTAMPTZ
        );

        CREATE TABLE path_claims (
            id INTEGER PRIMARY KEY,
            state TEXT,
            owner_kind TEXT,
            owner_item_id INTEGER
        );
    """),
    )
    from yoke_core.domain.workflow_registry import converge_builtin_workflows
    from yoke_core.domain.workflow_schema import ensure_workflow_schema

    ensure_workflow_schema(conn)
    converge_builtin_workflows(conn)
    return conn


def _args(**kw) -> DoctorArgs:
    return DoctorArgs(**{"project": "yoke", **kw})


def _run_hc(fn, conn=None, **kw):
    """Run a single HC and return the RecordCollector."""
    owns_conn = conn is None
    if owns_conn:
        conn = _make_conn()
    rec = RecordCollector()
    try:
        fn(conn, _args(**kw), rec)
    finally:
        if owns_conn:
            conn.close()
    return rec
