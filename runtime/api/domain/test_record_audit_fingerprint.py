"""Tests for migration_harness.record_audit_fingerprint and the
migration_audit table's final shape after the legacy ``status`` cutover.

These tests target ``yoke_core.domain.migration_harness`` even though the
shared schema bootstrap they exercise lives next to the coordination-lease
tests; previously they were colocated in test_coordination_leases.py.
"""

from __future__ import annotations

import pytest

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _get_columns
from yoke_core.domain.schema_init_apply import execute_schema_script
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


def _connect(db_path: str):
    """Readback connection to an :func:`init_test_db` database.

    Must be called inside the active ``with init_test_db(...)`` block so the
    Postgres DSN repoint is still live.
    """
    return connect_test_db(db_path)


_CONSTRAINED_AUDIT_DDL = """
    CREATE TABLE migration_audit (
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
        state TEXT NOT NULL CHECK(state IN ('planned'))
            DEFAULT 'planned',
        failure_reason TEXT,
        exception_reason TEXT,
        started_at TEXT NOT NULL,
        completed_at TEXT,
        duration_ms INTEGER
    );
"""


def _apply_constrained_audit_schema() -> None:
    """``apply_schema`` strategy: a ``migration_audit`` whose ``state`` CHECK
    only admits ``'planned'`` so the always-``'completed'`` fingerprint write
    trips a constraint violation. Resolves its connection through the backend
    factory so the constrained table lives on the repointed ``YOKE_PG_DSN``
    database the fingerprint writer actually targets.
    """
    conn = db_backend.connect()
    try:
        execute_schema_script(conn, _CONSTRAINED_AUDIT_DDL)
        conn.commit()
    finally:
        conn.close()


class TestMigrationAuditFinalShape:
    """migration_audit final shape after the migration-audit cutover cutover: ``state``
    is the sole live status surface; the legacy ``status`` column is
    gone and ``failure_reason`` carries failure-only semantics alongside
    the dedicated ``exception_reason`` column."""

    def test_final_columns_present(self, tmp_path) -> None:
        with init_test_db(tmp_path) as db_path:
            conn = _connect(db_path)
            try:
                cols = set(_get_columns(conn, "migration_audit"))
            finally:
                conn.close()
        expected = {
            "id", "migration_name", "description", "tables_declared",
            "expected_deltas", "pre_row_counts", "post_row_counts",
            "pre_fk_violations", "post_fk_violations", "backup_path",
            "state", "failure_reason", "exception_reason",
            "source_fingerprint", "rehearsed_at", "lease_id",
            "test_copy_path", "baseline_verify_result",
            "author_verify_result", "session_id", "model_name",
            "project_id", "started_at", "completed_at", "duration_ms",
            "actor_id", "worktree", "source_branch", "source_commit",
            "integration_target", "change_class",
        }
        assert expected == cols
        assert "status" not in cols


class TestRecordAuditFingerprint:
    """``record_audit_fingerprint`` writes only the ``state`` surface."""

    def test_fingerprint_records_state_completed(self, tmp_path) -> None:
        from yoke_core.domain.migration_harness import record_audit_fingerprint

        with init_test_db(tmp_path) as db_path:
            record_audit_fingerprint(
                db_path=db_path,
                name="test-exception-helper",
                description="run ad hoc cleanup",
                tables=["items"],
                pre_counts={"items": 5},
                post_counts={"items": 5},
                exception_reason=(
                    "historical maintenance — decision record paired"
                ),
                model_name="primary",
                project_id=1,
                session_id="sess-1",
            )
            conn = _connect(db_path)
            try:
                row = conn.execute(
                    "SELECT state, failure_reason, exception_reason, "
                    "model_name, project_id, session_id FROM migration_audit "
                    "WHERE migration_name = %s",
                    ("test-exception-helper",),
                ).fetchone()
            finally:
                conn.close()
        assert row is not None
        assert row["state"] == "completed"
        assert row["failure_reason"] is None
        assert row["exception_reason"] == "historical maintenance — decision record paired"
        assert row["model_name"] == "primary"
        assert row["project_id"] == 1
        assert row["session_id"] == "sess-1"

    def test_no_backup_fingerprint_requires_exception_reason(
        self, tmp_path
    ) -> None:
        """No-backup callers must carry their typed justification."""
        from yoke_core.domain.migration_harness import record_audit_fingerprint

        with init_test_db(tmp_path) as db_path:
            record_audit_fingerprint(
                db_path=db_path,
                name="no-backup-helper",
                description="minimal exception-path usage",
                tables=["items"],
                pre_counts={"items": 5},
                post_counts={"items": 5},
                exception_reason="bounded no-backup exception",
            )
            conn = _connect(db_path)
            try:
                row = conn.execute(
                    "SELECT state, failure_reason, exception_reason, "
                    "backup_path FROM migration_audit "
                    "WHERE migration_name = %s",
                    ("no-backup-helper",),
                ).fetchone()
            finally:
                conn.close()
        assert row["state"] == "completed"
        assert row["failure_reason"] is None
        assert row["exception_reason"] == "bounded no-backup exception"
        assert row["backup_path"] == ""

    def test_insert_failure_raises_audit_emission_error(
        self, tmp_path
    ) -> None:
        """Fail-closed contract: a DB error during the INSERT propagates as
        :class:`AuditEmissionError` rather than being silently swallowed.

        The restrictive ``migration_audit`` (``state`` constrained to
        ``'planned'``) is built on the backend-resolved test DB so the
        always-``'completed'`` write trips the psycopg ``CheckViolation``
        (an ``IntegrityError`` subclass). ``record_audit_fingerprint``
        writes through the facade to the repointed DSN (``db_path`` is
        ignored), so the table must live there, not in a stray on-disk
        file."""

        from yoke_core.domain.migration_harness import (
            AuditEmissionError,
            record_audit_fingerprint,
        )

        with init_test_db(
            tmp_path, apply_schema=_apply_constrained_audit_schema
        ) as db_path:
            with pytest.raises(AuditEmissionError) as excinfo:
                record_audit_fingerprint(
                    db_path=db_path,
                    name="failing-helper",
                    description="constraint violation",
                    tables=["items"],
                    pre_counts={"items": 0},
                    post_counts={"items": 0},
                    exception_reason="bounded no-backup exception",
                )
        assert "failing-helper" in str(excinfo.value)
