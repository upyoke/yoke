"""Shared module-level helpers for doctor_db test files.

Underscore prefix keeps pytest from collecting this as a test module.
Used by test_doctor_db.py and its split siblings.

The shared minimal-schema ``conn`` fixture (and its :data:`_MAKE_CONN_DDL`)
is consolidated here to avoid 4x duplication across split files. The local
items table is intentionally slim because the consuming health-check tests
insert partial rows.

The ``conn`` fixture builds the minimal schema through the Postgres test DB
factory. Consuming test files import ``conn`` into their namespace and take it
as a fixture parameter; the dialect-portable HC SQL runs against the same
connection shape as runtime code.
"""

from __future__ import annotations

import textwrap
from datetime import datetime, timedelta, timezone
from typing import Optional

import pytest

from yoke_core.engines.doctor import (
    CheckResult,
    DoctorArgs,
    RecordCollector,
)
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl


def _p(conn) -> str:
    """Parameter marker for the active test connection."""
    from yoke_core.domain import db_backend

    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _iso_offset(**kwargs) -> str:
    """Return a UTC timestamp offset from now."""
    return (datetime.now(timezone.utc) + timedelta(**kwargs)).strftime("%Y-%m-%d %H:%M:%S")


# Intentional minimal items table — see ``test_schema_fixture_derivation``
# residue exemption. Doctor-DB health checks query a slim column subset
# and the tests that consume this helper insert rows without ``created_at``
# / ``updated_at`` so they cannot adopt canonical NOT NULL constraints
# without broadening the consuming test setup.
_MAKE_CONN_DDL = textwrap.dedent("""\
        CREATE TABLE items (
            id INTEGER PRIMARY KEY,
            title TEXT,
            type TEXT,
            status TEXT,
            priority TEXT,
            project_id INTEGER DEFAULT 1,
            project_sequence INTEGER,
            github_issue TEXT,
            flow TEXT,
            rework_count INTEGER,
            deployed_to TEXT,
            updated_at TEXT,
            worktree TEXT,
            spec TEXT,
            deployment_flow TEXT,
            blocked INTEGER DEFAULT 0,
            blocked_reason TEXT,
            frozen INTEGER DEFAULT 0
        );

        CREATE TABLE epic_tasks (
            epic_id INTEGER,
            task_num INTEGER,
            title TEXT,
            status TEXT,
            last_heartbeat TEXT,
            dispatch_attempts INTEGER DEFAULT 0,
            PRIMARY KEY (epic_id, task_num)
        );

        CREATE TABLE shepherd_verdicts (
            id INTEGER PRIMARY KEY,
            item TEXT,
            transition TEXT,
            worker TEXT,
            verdict TEXT,
            caveats TEXT
        );

        CREATE TABLE caveat_dispositions (
            id INTEGER PRIMARY KEY,
            verdict_id INTEGER
        );

        CREATE TABLE deployment_flows (
            id TEXT PRIMARY KEY,
            project_id INTEGER,
            name TEXT,
            stages TEXT
        );

        CREATE TABLE deployment_runs (
            id TEXT PRIMARY KEY,
            project_id INTEGER,
            status TEXT,
            current_stage TEXT,
            started_at TEXT,
            created_at TEXT,
            completed_at TEXT,
            created_by TEXT
        );

        CREATE TABLE deployment_run_items (
            run_id TEXT,
            item_id INTEGER,
            PRIMARY KEY (run_id, item_id)
        );

        CREATE TABLE deployment_run_qa (
            id INTEGER PRIMARY KEY,
            run_id TEXT,
            check_name TEXT,
            blocking INTEGER,
            status TEXT
        );

        CREATE TABLE deployment_preview_environments (
            id INTEGER PRIMARY KEY,
            project_id INTEGER,
            env_name TEXT,
            run_id TEXT,
            status TEXT
        );

        CREATE TABLE qa_requirements (
            id INTEGER PRIMARY KEY,
            item_id INTEGER,
            epic_id INTEGER,
            task_num INTEGER,
            qa_kind TEXT,
            qa_phase TEXT,
            success_policy TEXT,
            deployment_run_id TEXT,
            waived_at TEXT,
            created_at TEXT
        );

        CREATE TABLE qa_runs (
            id INTEGER PRIMARY KEY,
            qa_requirement_id INTEGER,
            executor_type TEXT,
            verdict TEXT,
            raw_result TEXT
        );

        CREATE TABLE qa_artifacts (
            id INTEGER PRIMARY KEY,
            qa_run_id INTEGER,
            artifact_type TEXT,
            path TEXT
        );

        CREATE TABLE events (
            id INTEGER PRIMARY KEY,
            event_name TEXT,
            event_type TEXT,
            item_id TEXT,
            envelope TEXT,
            created_at TEXT
        );

        CREATE TABLE item_status_transitions (
            id INTEGER PRIMARY KEY,
            item_id INTEGER NOT NULL,
            task_num INTEGER,
            from_status TEXT,
            to_status TEXT NOT NULL,
            source TEXT,
            session_id TEXT,
            actor_id INTEGER,
            project_id INTEGER,
            created_at TEXT NOT NULL DEFAULT '2026-01-01T00:00:00Z'
        );

        CREATE TABLE ephemeral_environments (
            id INTEGER PRIMARY KEY,
            item TEXT,
            project_id INTEGER,
            branch TEXT,
            status TEXT
        );

        CREATE TABLE projects (
            id INTEGER PRIMARY KEY,
            slug TEXT UNIQUE,
            name TEXT,
            default_branch TEXT,
            created_at TEXT,
            github_repo TEXT,
            public_item_prefix TEXT DEFAULT 'YOK'
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
            (2, 'buzz', 'Buzz', 'main',
             '2026-01-01T00:00:00Z', 'example-org/buzz', 'BUZ');
    """)


def apply_make_conn_schema() -> None:
    """``apply_schema`` strategy applying :data:`_MAKE_CONN_DDL`.

    Resolves its connection through the repointed ``YOKE_PG_DSN``, satisfying
    :func:`runtime.api.fixtures.file_test_db.init_test_db`'s zero-arg
    ``apply_schema`` contract. Doctor HCs probe this minimal schema through
    backend-aware catalog helpers.
    """
    from yoke_core.domain import db_backend

    conn = db_backend.connect()
    try:
        apply_fixture_ddl(conn, _MAKE_CONN_DDL)
    finally:
        conn.close()


@pytest.fixture
def conn(tmp_path):
    """Postgres doctor-DB test connection with the minimal HC schema.

    A disposable per-test database is dropped on teardown. The connection
    follows runtime's current connection contract, so dialect-portable HC SQL
    (``now_sql`` / ``json_get`` / date functions) runs against native Postgres.
    """
    from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db

    with init_test_db(tmp_path, apply_schema=apply_make_conn_schema) as path:
        c = connect_test_db(path)
        try:
            yield c
        finally:
            c.close()


def _default_args(**overrides) -> DoctorArgs:
    args = DoctorArgs()
    for k, v in overrides.items():
        setattr(args, k, v)
    return args


def _get_result(rec: RecordCollector, check_id: str) -> Optional[CheckResult]:
    for r in rec.results:
        if r.check_id == check_id:
            return r
    return None
