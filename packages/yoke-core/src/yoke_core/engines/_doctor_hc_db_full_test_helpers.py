"""Shared module-level helpers for doctor_hc_db_full test files.

Underscore prefix keeps pytest from collecting this as a test module.
Used by test_doctor_hc_db_full.py and its split siblings.

Non-fixture helpers — plain Python functions invoked directly. Schema
helpers are consolidated here to avoid duplication across split files.
"""

from __future__ import annotations

from yoke_core.engines.doctor import DoctorArgs, RecordCollector
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl


def _default_args(**overrides) -> DoctorArgs:
    defaults = dict(only=None, quick=False, file=None, fix=False, project="yoke")
    defaults.update(overrides)
    return DoctorArgs(**defaults)


def _run_hc(hc_func, conn, **kwargs):
    """Run a single HC function and return the RecordCollector."""
    args = _default_args(**kwargs)
    rec = RecordCollector()
    hc_func(conn, args, rec)
    return rec


def _result(rec: RecordCollector, idx: int = 0):
    """Return the first (or idx-th) CheckResult."""
    return rec.results[idx]


def _add_ephemeral_environments_table(conn):
    """Add ephemeral_environments table (not in conftest schema)."""
    apply_fixture_ddl(
        conn,
        """
        CREATE TABLE IF NOT EXISTS ephemeral_environments (
            id INTEGER PRIMARY KEY,
            project_id INTEGER NOT NULL,
            branch TEXT NOT NULL,
            item TEXT,
            workflow_run_id TEXT,
            github_ref TEXT,
            port_api INTEGER,
            port_web INTEGER,
            url TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            started_at TEXT,
            stopped_at TEXT,
            health_check_url TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(project_id, branch)
        );
        """,
    )


def _add_deployment_preview_environments_table(conn):
    """Add deployment_preview_environments table (not in conftest schema)."""
    apply_fixture_ddl(
        conn,
        """
        CREATE TABLE IF NOT EXISTS deployment_preview_environments (
            id INTEGER PRIMARY KEY,
            project_id INTEGER NOT NULL,
            env_name TEXT NOT NULL,
            run_id TEXT,
            status TEXT NOT NULL DEFAULT 'available',
            env_type TEXT NOT NULL DEFAULT 'adhoc',
            url TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(project_id, env_name)
        );
        """,
    )
