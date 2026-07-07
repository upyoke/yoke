"""Backup and restore helpers for governed migration harness flows."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from yoke_core.domain.migration_harness_contract import MigrationBackupError


def create_exception_backup(db_path: str, reason: str) -> str:
    """Create a Postgres rollback backup for an exception-path mutation.

    The retired root SQLite backup CLI is no longer an active rollback
    substrate. Exception-path callers with a real ``backup_reason`` now
    reuse the same Postgres dump helper as ``migration_apply`` and fail
    closed when the Postgres target cannot be resolved.

    Raises :class:`MigrationBackupError` on any backup failure so
    :func:`record_audit_fingerprint` can surface a fail-closed error
    rather than emit an audit row that points at a missing backup.
    """
    if not isinstance(reason, str) or not reason.strip():
        # Caller bug, not a backup-substrate failure — keep the error
        # taxonomy honest so MigrationBackupError stays scoped to real
        # backup-creation failures (disk full, permission denied, etc.).
        raise ValueError(
            f"create_exception_backup: reason must be a non-empty string "
            f"(got {reason!r})."
        )
    canonical_reason = (
        reason
        if reason.startswith("pre-migration-")
        else f"pre-migration-{reason}"
    )
    return _run_postgres_backup(
        canonical_reason,
        worktree_path=_infer_backup_worktree_path(db_path),
        label=f"exception-path backup failed for {reason!r}",
    )


def _run_backup(db_path: str, reason: str) -> str:
    """Fail closed for the retired SQLite-file governed harness."""
    del db_path, reason
    raise MigrationBackupError(
        "GovernedMigration pre-flight backups through "
        "yoke_core.domain.backup are retired. Use "
        "`python3 -m yoke_core.domain.migration_apply rehearse YOK-N` "
        "followed by `python3 -m yoke_core.domain.migration_apply "
        "live-apply YOK-N`; live-apply creates the Postgres rollback dump "
        "recorded in migration_audit.backup_path."
    )


def _run_postgres_backup(reason: str, *, worktree_path: Path, label: str) -> str:
    from yoke_core.domain import db_backend
    from yoke_core.domain.migration_apply_targets import (
        DbTarget,
        create_rollback_backup,
    )

    try:
        target = DbTarget(
            kind="postgres",
            target=db_backend.resolve_pg_dsn(),
            display="postgres:authority",
        )
        return create_rollback_backup(target, reason, worktree_path=worktree_path)
    except MigrationBackupError:
        raise
    except Exception as exc:  # RuntimeError, MigrationApplyError, OSError, etc.
        raise MigrationBackupError(
            f"{label}: Postgres rollback backup failed: {exc}"
        ) from exc


def _infer_backup_worktree_path(db_path: str) -> Path:
    candidate = Path(db_path)
    if candidate.name.startswith("yoke.db") and candidate.parent.name == "data":
        return candidate.parent.parent
    if candidate.parent != Path("."):
        return candidate.parent

    from yoke_core.api.repo_root import find_repo_root

    return find_repo_root(Path(__file__))


def _restore_backup(db_path: str, backup_path: str) -> None:
    """Restore DB from backup using sqlite3 .restore or file copy."""
    if not os.path.isfile(backup_path):
        raise MigrationBackupError(f"Backup file not found: {backup_path}")

    # Close any connections before restore by using file copy
    # (sqlite3 .restore requires an open connection which is tricky mid-rollback)
    shutil.copy2(backup_path, db_path)
