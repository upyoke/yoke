"""Legacy governed migration harness for explicit SQLite validation files.

Yoke authority is Postgres-native. Active governed migration apply routes
through the migration model target layer, where rollback backups use
Postgres-native dump artifacts. This module remains as a compatibility front
door for legacy file-shaped tests. Path-based audit CLI commands fail closed,
and preflight SQLite backup entrypoints fail closed.

Usage from Python::

    from yoke_core.domain.migration_harness import GovernedMigration

    with GovernedMigration(
        name="migrate-check-constraints",
        tables=["items"],
        expected_deltas={"items": 0},
        description="Rebuild items table with CHECK constraints",
        db_path="/path/to/explicit-validation.sqlite3",
    ) as gm:
        conn = gm.conn
        # ... do rename-copy-drop DDL ...

If post-flight verification fails in a patched legacy test harness, the harness
auto-restores the DB from the supplied file backup and raises
``MigrationVerificationError``.

Retired CLI usage (fail closed for shell callers)::

    python3 -m yoke_core.domain.migration_harness verify <db-path>
    python3 -m yoke_core.domain.migration_harness audit-list <db-path>

Exit codes: 0 success, 1 error, 2 usage.
"""
from __future__ import annotations

from yoke_core.domain import migration_harness_audit as _audit
from yoke_core.domain import migration_harness_core as _core
from yoke_core.domain.migration_harness_backup import (
    _restore_backup,
    _run_backup,
    create_exception_backup,
)
from yoke_core.domain.migration_harness_checks import _count_all_tables, _fk_violation_count
from yoke_core.domain.migration_harness_cli import cmd_audit_list, cmd_verify, main
from yoke_core.domain.migration_harness_contract import (
    AUDIT_TABLE, CRITICAL_TABLES, AuditEmissionError, MigrationBackupError,
    MigrationVerificationError,
)
from yoke_core.domain.migration_harness_events import _emit_event


def _sync_core_hooks() -> None:
    _core._run_backup = _run_backup
    _core._restore_backup = _restore_backup
    _core._emit_event = _emit_event


class GovernedMigration(_core.GovernedMigration):
    """Compatibility front door for patchable harness internals."""

    def __enter__(self):
        _sync_core_hooks()
        return super().__enter__()

    def _complete(self) -> None:
        _sync_core_hooks()
        return super()._complete()

    def _rollback(self, reason: str) -> None:
        _sync_core_hooks()
        return super()._rollback(reason)


def record_audit_fingerprint(*args, **kwargs):
    _audit.create_exception_backup = create_exception_backup
    return _audit.record_audit_fingerprint(*args, **kwargs)

__all__ = [
    "AUDIT_TABLE", "CRITICAL_TABLES", "AuditEmissionError",
    "GovernedMigration", "MigrationBackupError",
    "MigrationVerificationError", "cmd_audit_list", "cmd_verify",
    "create_exception_backup", "main", "record_audit_fingerprint",
    "_count_all_tables", "_fk_violation_count",
    "_emit_event", "_restore_backup", "_run_backup",
]

if __name__ == "__main__":
    main()
