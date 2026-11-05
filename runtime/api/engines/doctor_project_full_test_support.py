# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

from pathlib import Path

from typing import Any

from unittest.mock import patch

from yoke_core.engines.doctor import (
    DoctorArgs,
    RecordCollector,
    hc_project_deploy_flows,
    hc_project_health,
    hc_project_lookup,
    hc_project_repo_exists,
    hc_project_worktrees,
)

from runtime.api.fixtures.machine_config_test import (
    clear_machine_checkout,
    register_machine_checkout,
)


def _make_conn() -> Any:
    """Disposable Postgres test DB; dropped when the conn is closed or GC'd."""
    from runtime.api.fixtures import pg_testdb
    from runtime.api.fixtures.schema_ddl import apply_fixture_ddl

    name = pg_testdb.create_test_database()
    conn = pg_testdb.drop_database_on_close(
        pg_testdb.connect_test_database(name),
        name,
    )
    apply_fixture_ddl(
        conn,
        """
        CREATE TABLE projects (
            id INTEGER PRIMARY KEY,
            slug TEXT UNIQUE NOT NULL,
            name TEXT,
            github_repo TEXT,
            public_item_prefix TEXT DEFAULT 'YOK'
        );

        CREATE TABLE project_capabilities (
            id INTEGER PRIMARY KEY,
            project_id INTEGER,
            type TEXT,
            settings TEXT,
            created_at TIMESTAMPTZ
        );

        CREATE TABLE deployment_flows (
            id TEXT PRIMARY KEY,
            project_id INTEGER,
            stages TEXT
        );
        """,
    )
    return conn


def _project_id(project: str) -> int:
    return {"yoke": 1, "externalwebapp": 2}.get(project, 99)


def _seed_project(
    conn: Any,
    project: str,
    checkout_path: str | None = None,
    github_repo: str | None = None,
) -> None:
    project_id = _project_id(project)
    if checkout_path and Path(checkout_path).is_dir():
        checkout = Path(checkout_path)
        register_machine_checkout(checkout.parent, checkout, project_id)
    else:
        clear_machine_checkout(project_id)
    conn.execute(
        "INSERT INTO projects "
        "(id, slug, name, github_repo, public_item_prefix) "
        "VALUES (%s, %s, %s, %s, 'YOK') "
        "ON CONFLICT(id) DO NOTHING",
        (project_id, project, project.title(), github_repo),
    )


def _seed_capability(
    conn: Any,
    project: str,
    cap_type: str,
    settings: str,
) -> None:
    _seed_project(conn, project)
    conn.execute(
        "INSERT INTO project_capabilities (project_id, type, settings) "
        "VALUES (%s, %s, %s)",
        (_project_id(project), cap_type, settings),
    )


def _args(**overrides) -> DoctorArgs:
    defaults = dict(
        file=None,
        fix=False,
        only=None,
        quick=False,
        project="externalwebapp",
        db_path=None,
    )
    defaults.update(overrides)
    return DoctorArgs(**defaults)


def _run_hc(fn, conn=None, **kwargs) -> RecordCollector:
    if conn is None:
        conn = _make_conn()
    rec = RecordCollector()
    fn(conn, _args(**kwargs), rec)
    return rec
