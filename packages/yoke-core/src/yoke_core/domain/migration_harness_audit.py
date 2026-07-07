"""Audit-fingerprint exception pathway for governed migration evidence."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.migration_harness_backup import create_exception_backup
from yoke_core.domain.migration_harness_contract import AuditEmissionError

def record_audit_fingerprint(
    db_path: str,
    name: str,
    description: str,
    tables: List[str],
    pre_counts: Dict[str, int],
    post_counts: Dict[str, int],
    *,
    backup_reason: Optional[str] = None,
    exception_reason: Optional[str] = None,
    model_name: Optional[str] = None,
    project_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> str:
    """Insert a completed migration_audit row for operations that have
    their own safety model but need to be discoverable.

    Explicit documented exception path. Use from destructive maintenance
    helpers bounded by their own contract (retention pruning, envelope
    repair, in-place backfill rewrites) so doctor HCs can see the
    operation happened. Every call site must be paired with a decision
    record at ``docs/archive/decisions/<name>.md``;
    ``HC-oneshot-migration-coverage`` enforces the pairing.

    Backup policy. ``backup_reason`` decides whether the helper creates
    a rollback artifact before recording the audit row:

      * ``backup_reason=<non-empty-str>`` — the helper calls
        :func:`create_exception_backup` to create a Postgres rollback
        dump through the same target helper used by governed migration
        apply, then stores the resulting path in ``backup_path``.
      * ``backup_reason=None`` (default) — no backup is created and the
        ``backup_path`` column is written as the empty string. This
        branch is reserved for bounded callers whose safety argument
        does not require a rollback copy (for example retention
        prunes). ``exception_reason`` is required on this branch so the
        audit row carries the typed no-backup justification.
      * ``backup_reason=""`` — rejected with :class:`ValueError`. The
        empty-string form historically produced silently-unbacked audit
        rows; callers must choose either ``None`` (explicit no-backup)
        or a meaningful reason slug.

    Fail-closed contract. The helper is load-bearing for the governed
    exception pathway — the audit row is the only durable evidence that
    the exception fired. If ``backup_reason`` is set and Postgres rollback
    backup creation fails, :class:`MigrationBackupError` propagates BEFORE
    any audit row is inserted so the operator sees a loud failure instead
    of a row pointing at a missing file. Any database error raised while
    inserting the row is re-raised as
    :class:`AuditEmissionError` so that failure mode is also visible.

    Callers MUST pre-compute table row counts before and after the
    destructive operation and pass both. The audit row is marked
    ``state='completed'`` unconditionally — this helper does not verify
    deltas; it only makes the event discoverable.

    Exception-path provenance. Set ``exception_reason`` to the
    documented justification that the caller's paired decision record
    expands on. It lands in the dedicated ``exception_reason`` column.
    The ``failure_reason`` column is reserved for the matching
    ``*_failed`` ``state`` values and is never populated here.

    Optional fields ``model_name`` / ``project_id`` / ``session_id``
    fill the corresponding audit columns when the caller has them.

    Returns the canonical ``backup_path`` stored on the row — either
    the absolute path of the created backup file or the empty string
    for the no-backup branch.
    """
    if backup_reason is not None:
        if not isinstance(backup_reason, str) or not backup_reason.strip():
            raise ValueError(
                "record_audit_fingerprint: backup_reason must be either "
                "None (explicit no-backup, documented in exception_reason) "
                "or a non-empty reason slug. Empty strings historically "
                "created silently-unbacked audit rows and are no longer "
                "accepted."
            )
        backup_path = create_exception_backup(db_path, backup_reason)
    else:
        if not isinstance(exception_reason, str) or not exception_reason.strip():
            raise ValueError(
                "record_audit_fingerprint: backup_reason=None is the "
                "explicit no-backup branch and requires a non-empty "
                "exception_reason justification."
            )
        backup_path = ""

    conn = db_backend.connect(db_path)
    try:
        now = iso8601_now()
        expected_deltas = {
            tbl: post_counts.get(tbl, 0) - pre_counts.get(tbl, 0)
            for tbl in tables
        }
        columns: List[str] = [
            "migration_name", "description", "tables_declared",
            "expected_deltas", "pre_row_counts", "post_row_counts",
            "pre_fk_violations", "post_fk_violations", "backup_path",
            "state", "started_at", "completed_at", "duration_ms",
        ]
        values: List[Any] = [
            name,
            description,
            json.dumps(tables),
            json.dumps(expected_deltas),
            json.dumps(pre_counts),
            json.dumps(post_counts),
            0,
            0,
            backup_path,
            "completed",
            now,
            now,
            0,
        ]
        for column, value in (
            ("exception_reason", exception_reason),
            ("model_name", model_name),
            ("project_id", project_id),
            ("session_id", session_id),
        ):
            if value is not None:
                columns.append(column)
                values.append(value)

        placeholders = ", ".join("%s" for _ in columns)
        conn.execute(
            f"INSERT INTO migration_audit ({', '.join(columns)}) "
            f"VALUES ({placeholders})",
            tuple(values),
        )
        conn.commit()
    except (
        *db_backend.integrity_error_types(),
        *db_backend.operational_error_types(),
    ) as exc:
        # Fail closed: a constraint/relation error during the INSERT becomes
        # AuditEmissionError instead of silently losing governed evidence.
        raise AuditEmissionError(
            f"record_audit_fingerprint failed for {name!r}: {exc}"
        ) from exc
    finally:
        conn.close()

    return backup_path
