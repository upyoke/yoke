# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

import textwrap

from unittest.mock import patch

import pytest

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_ISSUES_READ_PERMISSION_LEVELS,
)

from yoke_core.domain.item_worktree_schema import ITEM_WORKTREES_TABLE_SQL

from yoke_core.engines._project_identity_test_helpers import (
    _insert_item,
    _seed_project,
)

from yoke_core.engines.doctor import (
    DoctorArgs,
    RecordCollector,
    hc_gh_orphan_detection,
    hc_orphaned_gh_issues,
    hc_wrong_repo_issues,
)

from runtime.api.api_workflow_test_helpers import (
    install_workflow_registry_and_pin_items,
)

from runtime.api.fixtures import pg_testdb

from runtime.api.fixtures.schema_ddl import apply_fixture_ddl


@pytest.fixture(autouse=True)
def _self_project_is_yoke(monkeypatch):
    """The installation's self project is ``yoke`` in these fixtures."""
    monkeypatch.setattr(
        "yoke_core.engines.doctor_hc_worktrees_gh_repo.self_project_names",
        lambda conn: frozenset({"1", "yoke"}),
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
            status TEXT,
            priority TEXT,
            project_id INTEGER DEFAULT 1,
            project_sequence INTEGER,
            github_issue TEXT,
            deployed_to TEXT,
            updated_at TIMESTAMPTZ,
            deployment_flow TEXT
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
            public_item_prefix TEXT DEFAULT 'YOK',
            github_sync_mode TEXT NOT NULL DEFAULT 'disabled'
        );
        INSERT INTO projects
            (id, slug, name, default_branch, created_at,
             github_repo, public_item_prefix, github_sync_mode)
        VALUES
            (1, 'yoke', 'Yoke', 'main',
             '2026-01-01T00:00:00Z', 'upyoke/yoke', 'YOK', 'enabled');

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
    """)
        + ITEM_WORKTREES_TABLE_SQL,
    )
    install_workflow_registry_and_pin_items(conn)
    return conn


def _make_completed(returncode=0, stdout="", stderr=""):
    """Create a mock CompletedProcess."""
    import subprocess

    return subprocess.CompletedProcess([], returncode, stdout, stderr)
