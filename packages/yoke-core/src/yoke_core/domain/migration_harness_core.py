"""Legacy SQLite-file GovernedMigration context manager implementation."""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from typing import Dict, List, Optional

from yoke_core.domain.db_helpers import BUSY_TIMEOUT_MS, iso8601_now
from yoke_core.domain.migration_harness_backup import _restore_backup, _run_backup
from yoke_core.domain.migration_harness_checks import _count_all_tables, _fk_violation_count
from yoke_core.domain.migration_harness_contract import CRITICAL_TABLES, MigrationBackupError, MigrationVerificationError
from yoke_core.domain.migration_harness_events import _emit_event

class GovernedMigration:
    """Legacy context manager for explicit SQLite validation files.

    Yoke authority is Postgres-native. Active governed migration apply uses
    the migration model target layer and its Postgres rollback backup path;
    the unpatched SQLite-file backup path in this class fails closed.

    Pre-flight:
        1. Fail-closed retired backup check; use ``migration_apply`` for
           Postgres rollback dumps.
        2. Baseline row counts for ALL tables
        3. Baseline FK violation count
        4. Audit record insertion

    The caller performs DDL within the ``with`` block using ``gm.conn``.

    Post-flight (on clean exit):
        1. Re-count all tables, compare against baseline + declared deltas
        2. Re-check FK integrity
        3. Verify unaffected tables unchanged
        4. Update audit record

    Rollback (on verification failure or exception):
        1. Auto-restore from pre-flight backup
        2. Emit CRITICAL event
        3. Update audit record with failure reason
    """

    def __init__(
        self,
        name: str,
        tables: List[str],
        expected_deltas: Dict[str, int],
        description: str = "",
        db_path: Optional[str] = None,
        conn: Optional[sqlite3.Connection] = None,
    ):
        self.name = name
        self.tables = tables
        self.expected_deltas = expected_deltas
        self.description = description
        if db_path is None:
            raise ValueError(
                "GovernedMigration requires an explicit legacy SQLite "
                "validation/archive db_path. Active Yoke authority is "
                "Postgres-native; do not resolve data/yoke.db implicitly."
            )
        self.db_path = db_path
        self._external_conn = conn
        self.conn: Optional[sqlite3.Connection] = None
        self.backup_path: Optional[str] = None
        self.pre_counts: Dict[str, int] = {}
        self.post_counts: Dict[str, int] = {}
        self.pre_fk_violations: int = 0
        self.audit_id: Optional[int] = None
        self._start_time: Optional[datetime] = None

    def __enter__(self) -> "GovernedMigration":
        self._start_time = datetime.now(timezone.utc)

        # Step 1: Backup
        try:
            reason = f"pre-migration-{self.name}"
            self.backup_path = _run_backup(self.db_path, reason)
        except MigrationBackupError as exc:
            print(f"FATAL: Pre-flight backup failed: {exc}", file=sys.stderr)
            raise

        # Step 2: Connect
        if self._external_conn is not None:
            self.conn = self._external_conn
        else:
            self.conn = sqlite3.connect(self.db_path)
            self.conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")

        # Step 3: Baseline row counts
        self.pre_counts = _count_all_tables(self.conn)

        # Step 4: Baseline FK violations
        self.pre_fk_violations = _fk_violation_count(self.conn)

        # Step 5: Insert audit record. ``state='planned'`` is the sole
        # live status surface; schema.cmd_init owns the table shape.
        now = iso8601_now()
        cur = self.conn.execute(
            "INSERT INTO migration_audit ("
            "migration_name, description, tables_declared, expected_deltas, "
            "pre_row_counts, pre_fk_violations, backup_path, state, started_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
            (
                self.name,
                self.description,
                json.dumps(self.tables),
                json.dumps(self.expected_deltas),
                json.dumps(self.pre_counts),
                self.pre_fk_violations,
                self.backup_path or "",
                "planned",
                now,
            ),
        )
        self.audit_id = int(cur.fetchone()[0])
        self.conn.commit()

        print(f"[migration-harness] {self.name}: pre-flight complete", file=sys.stderr)
        print(f"  backup: {self.backup_path}", file=sys.stderr)
        for tbl in self.tables:
            print(f"  {tbl}: {self.pre_counts.get(tbl, '?')} rows", file=sys.stderr)

        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        if exc_type is not None:
            # Exception during migration body — rollback
            self._rollback(f"exception: {exc_type.__name__}: {exc_val}")
            return False  # re-raise

        # Post-flight verification
        try:
            self._verify()
        except MigrationVerificationError as exc:
            self._rollback(str(exc))
            raise

        # Success path
        self._complete()
        return False

    def _verify(self) -> None:
        """Post-flight verification checks."""
        assert self.conn is not None

        # Re-count all tables
        self.post_counts = _count_all_tables(self.conn)

        failures: List[str] = []

        # Check 1: Declared tables match expected deltas
        for tbl in self.tables:
            pre = self.pre_counts.get(tbl, 0)
            post = self.post_counts.get(tbl, 0)
            expected_delta = self.expected_deltas.get(tbl, 0)
            expected_post = pre + expected_delta

            if post != expected_post:
                failures.append(
                    f"{tbl}: expected {expected_post} rows (was {pre}, delta {expected_delta}), "
                    f"got {post}"
                )

        # Check 2: Unaffected critical tables unchanged
        for tbl in CRITICAL_TABLES:
            if tbl in self.tables:
                continue  # Already checked
            pre = self.pre_counts.get(tbl, 0)
            post = self.post_counts.get(tbl, 0)
            if pre != post:
                failures.append(
                    f"COLLATERAL: {tbl} changed from {pre} to {post} rows "
                    f"(not in declared tables)"
                )

        # Check 3: FK integrity (skip if either baseline errored with -1)
        post_fk = _fk_violation_count(self.conn)
        if self.pre_fk_violations >= 0 and post_fk >= 0:
            new_violations = post_fk - self.pre_fk_violations
            if new_violations > 0:
                failures.append(
                    f"FK violations: {new_violations} new "
                    f"(pre={self.pre_fk_violations}, post={post_fk})"
                )

        if failures:
            msg = (
                f"Migration '{self.name}' post-flight verification failed:\n"
                + "\n".join(f"  - {f}" for f in failures)
            )
            raise MigrationVerificationError(msg)

        print(f"[migration-harness] {self.name}: post-flight verification passed", file=sys.stderr)
        for tbl in self.tables:
            print(
                f"  {tbl}: {self.pre_counts.get(tbl, '?')} → {self.post_counts.get(tbl, '?')} rows",
                file=sys.stderr,
            )

    def _complete(self) -> None:
        """Record successful completion."""
        assert self.conn is not None
        now = iso8601_now()
        duration = None
        if self._start_time:
            delta = datetime.now(timezone.utc) - self._start_time
            duration = int(delta.total_seconds() * 1000)

        self.conn.execute(
            "UPDATE migration_audit SET "
            "state='completed', post_row_counts=?, post_fk_violations=?, "
            "completed_at=?, duration_ms=? WHERE id=?",
            (
                json.dumps(self.post_counts),
                _fk_violation_count(self.conn),
                now,
                duration,
                self.audit_id,
            ),
        )
        self.conn.commit()

        if self._external_conn is None and self.conn is not None:
            self.conn.close()

        _emit_event(
            self.db_path,
            "MigrationCompleted",
            {
                "migration": self.name,
                "tables": self.tables,
                "pre_counts": {t: self.pre_counts.get(t, 0) for t in self.tables},
                "post_counts": {t: self.post_counts.get(t, 0) for t in self.tables},
                "duration_ms": duration,
            },
            severity="INFO",
        )

        print(f"[migration-harness] {self.name}: completed successfully", file=sys.stderr)

    def _rollback(self, reason: str) -> None:
        """Auto-restore from backup and record failure."""
        print(
            f"[migration-harness] {self.name}: ROLLING BACK — {reason}",
            file=sys.stderr,
        )

        # Close connection before file-level restore
        if self._external_conn is None and self.conn is not None:
            try:
                self.conn.close()
            except Exception:
                pass

        # Restore from backup
        if self.backup_path and os.path.isfile(self.backup_path):
            try:
                _restore_backup(self.db_path, self.backup_path)
                print(
                    f"[migration-harness] Restored from: {self.backup_path}",
                    file=sys.stderr,
                )
            except Exception as exc:
                print(
                    f"[migration-harness] CRITICAL: restore failed: {exc}",
                    file=sys.stderr,
                )

        # Re-open to record audit (the restored DB may not have the original
        # audit record since backup was taken before it was inserted).
        # Exact failure-branch classification is left generic here; callers
        # with finer branch telemetry use ``migration_apply`` directly.
        try:
            audit_conn = sqlite3.connect(self.db_path)
            audit_conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
            now = iso8601_now()
            duration = None
            if self._start_time:
                delta = datetime.now(timezone.utc) - self._start_time
                duration = int(delta.total_seconds() * 1000)

            cur = audit_conn.execute(
                "UPDATE migration_audit SET "
                "state='live_apply_failed', failure_reason=?, "
                "post_row_counts=?, completed_at=?, duration_ms=? "
                "WHERE id=?",
                (
                    reason,
                    json.dumps(self.post_counts) if self.post_counts else None,
                    now,
                    duration,
                    self.audit_id,
                ),
            )
            if cur.rowcount == 0:
                audit_conn.execute(
                    "INSERT INTO migration_audit ("
                    "migration_name, description, tables_declared, "
                    "expected_deltas, pre_row_counts, pre_fk_violations, "
                    "backup_path, state, failure_reason, post_row_counts, "
                    "started_at, completed_at, duration_ms"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        self.name,
                        self.description,
                        json.dumps(self.tables),
                        json.dumps(self.expected_deltas),
                        json.dumps(self.pre_counts),
                        self.pre_fk_violations,
                        self.backup_path or "",
                        "live_apply_failed",
                        reason,
                        json.dumps(self.post_counts) if self.post_counts else None,
                        self._start_time.strftime("%Y-%m-%dT%H:%M:%SZ")
                        if self._start_time else now,
                        now,
                        duration,
                    ),
                )
            audit_conn.commit()
            audit_conn.close()
        except Exception:
            pass  # Best-effort audit update after restore

        _emit_event(
            self.db_path,
            "MigrationRolledBack",
            {
                "migration": self.name,
                "reason": reason,
                "backup_restored": self.backup_path or "",
            },
            severity="CRITICAL",
        )
