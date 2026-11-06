# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from typing import Any

from unittest.mock import patch

from yoke_core.engines.doctor import (
    DoctorArgs,
    HEALTH_CHECKS,
    _should_run_hc,
    hc_deploy_stage_integrity,
    hc_shepherd_spec_integrity,
    hc_stale_body,
)

from yoke_project_checks.check_docs import (
    hc_claudemd_drift,
)

from runtime.api.engines._doctor_hc_meta_full_test_helpers import (
    _NOW_INSTANT,
    _make_conn,
    _result,
    _run_hc,
)


def _ensure_migration_audit_table(conn: Any) -> None:
    """Create the final-shape migration_audit table on the test conn."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS migration_audit (
            id INTEGER PRIMARY KEY,
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
            rehearsed_at TIMESTAMPTZ,
            lease_id INTEGER,
            test_copy_path TEXT,
            baseline_verify_result TEXT,
            author_verify_result TEXT,
            session_id TEXT,
            model_name TEXT,
            project_id TEXT,
            started_at TIMESTAMPTZ NOT NULL,
            completed_at TIMESTAMPTZ,
            duration_ms INTEGER
        )
    """)
