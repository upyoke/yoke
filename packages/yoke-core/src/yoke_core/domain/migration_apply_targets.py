"""Backend-declared DB target helpers for governed migration apply."""

from __future__ import annotations

import os
import re
import sqlite3
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

from yoke_core.domain import db_backend, db_helpers
from yoke_core.domain import runtime_settings
from yoke_core.domain.migration_apply_contract import MigrationApplyError
from yoke_core.domain.migration_model_capability_validation import (
    DEFAULT_CONNECTION_ENV_VAR,
)
from yoke_core.domain.schema_fingerprint import fingerprint_kind
from yoke_core.domain.worktree_validation_surface import (
    provision_validation_surfaces,
    resolve_validation_db_paths,
)

POSTGRES_VALIDATION_ENV_SUFFIX = "_VALIDATION"


@dataclass(frozen=True)
class DbTarget:
    """A model-declared database target.

    ``target`` is the private connection value (path or DSN). ``display`` is
    safe operator/audit text and must not include secret-bearing DSN content.
    """

    kind: str
    target: str
    display: str


def resolve_connection_env_var(model: Mapping[str, Any]) -> str:
    runner = model.get("runner") or {}
    config = runner.get("config") or {}
    return str(config.get("connection_env_var") or DEFAULT_CONNECTION_ENV_VAR)


def resolve_authoritative_db_target(
    repo_path: Path, model: Mapping[str, Any]
) -> DbTarget:
    auth = model.get("authoritative_db") or {}
    kind = str(auth.get("kind") or "")
    if kind == "sqlite_file":
        location = auth.get("location") or {}
        rel = location.get("path")
        if not rel:
            raise MigrationApplyError(
                "authoritative_db.location.path missing on model declaration"
            )
        candidate = (repo_path / rel).resolve()
        return DbTarget(kind=kind, target=str(candidate), display=str(candidate))
    if kind == "postgres":
        try:
            target = db_backend.resolve_pg_dsn()
        except Exception as exc:  # noqa: BLE001
            raise MigrationApplyError(
                "authoritative_db.kind 'postgres' requires a resolved "
                "Postgres DSN from YOKE_PG_DSN, YOKE_PG_DSN_FILE, or "
                "connected-env credentials"
            ) from exc
        label = _dsn_dbname(target) or (
            (auth.get("location") or {}).get("database_name")
        ) or "authority"
        return DbTarget(kind=kind, target=target, display=f"postgres:{label}")
    raise MigrationApplyError(
        f"authoritative_db.kind {kind!r} is recognized but not wired for "
        "governed migration apply"
    )


def resolve_validation_db_target(
    *,
    worktree_path: Path,
    project: str,
    model_name: str,
    model: Mapping[str, Any],
    control_db_path: Optional[str],
) -> DbTarget:
    surface = model.get("validation_surface") or {}
    kind = surface.get("kind")
    if kind == "worktree_local_sqlite":
        return _resolve_worktree_local_sqlite_validation(
            worktree_path=worktree_path,
            project=project,
            model_name=model_name,
            control_db_path=control_db_path,
        )
    if kind == "external_validation":
        return _resolve_external_postgres_validation(model, model_name)
    raise MigrationApplyError(
        f"model '{model_name}' validation surface kind {kind!r} is not wired "
        "for governed migration rehearsal"
    )


def connect_db_target(target: DbTarget):
    if target.kind == "sqlite_file":
        conn = sqlite3.connect(target.target)
        conn.row_factory = sqlite3.Row
        conn.execute(f"PRAGMA busy_timeout = {db_helpers.BUSY_TIMEOUT_MS}")
        conn.execute("PRAGMA foreign_keys = ON")
        return conn
    if target.kind == "postgres":
        return db_backend.connect_psycopg(target.target)
    raise MigrationApplyError(
        f"database target kind {target.kind!r} is not connectable"
    )


def ensure_migration_audit_table_for_target(target: DbTarget, conn) -> None:
    """Ensure ``migration_audit`` exists using the target's native dialect."""
    if target.kind == "postgres":
        from yoke_core.domain.migration_audit_schema import (
            ensure_migration_audit_table_postgres,
        )

        ensure_migration_audit_table_postgres(conn)
        return
    from yoke_core.domain.migration_audit_schema import (
        ensure_migration_audit_table,
    )

    ensure_migration_audit_table(conn)


def fingerprint_db_target(target: DbTarget) -> str:
    return fingerprint_kind(target.kind, target.target)


def create_rollback_backup(
    target: DbTarget, reason: str, *, worktree_path: Path
) -> str:
    if target.kind == "sqlite_file":
        raise MigrationApplyError(
            "SQLite rollback backups through yoke_core.domain.backup are "
            "retired. Active governed migration apply must target Postgres; "
            "generic external SQLite validation/archive flows need their own "
            "explicit rollback/archive contract."
        )
    if target.kind == "postgres":
        return _create_postgres_dump_backup(target, reason, worktree_path)
    raise MigrationApplyError(
        f"rollback backup for database target kind {target.kind!r} is not wired"
    )


def _resolve_worktree_local_sqlite_validation(
    *,
    worktree_path: Path,
    project: str,
    model_name: str,
    control_db_path: Optional[str],
) -> DbTarget:
    provision = provision_validation_surfaces(
        worktree_path, project, db_path=control_db_path,
    )
    failure = next((s for s in provision.surfaces if s.error), None)
    if failure is not None:
        raise MigrationApplyError(
            f"validation surface provisioning failed for model "
            f"'{failure.model_name}': {failure.error}"
        )
    validation_paths = resolve_validation_db_paths(
        worktree_path, project, db_path=control_db_path,
    )
    entry = validation_paths.get(model_name)
    if entry is None:
        raise MigrationApplyError(
            f"model '{model_name}' has no worktree-local SQLite validation "
            "surface; SQLite validation is allowed only as a validation "
            "surface, never as authoritative DB fallback"
        )
    return DbTarget(
        kind="sqlite_file",
        target=entry["path"],
        display=entry["path"],
    )


def _resolve_external_postgres_validation(
    model: Mapping[str, Any], model_name: str
) -> DbTarget:
    authority_dsn = db_backend.resolve_pg_dsn()
    env_var = f"{resolve_connection_env_var(model)}{POSTGRES_VALIDATION_ENV_SUFFIX}"
    validation_dsn = os.environ.get(env_var, "").strip()
    if not validation_dsn:
        raise MigrationApplyError(
            f"model '{model_name}' uses external_validation; set {env_var} "
            "to a validation-only Postgres DSN for rehearsal. The "
            "authoritative Postgres DSN is never used as the rehearsal target."
        )
    if validation_dsn == authority_dsn:
        raise MigrationApplyError(
            f"{env_var} matches the authoritative Postgres DSN; rehearsal "
            "requires a separate validation-only Postgres database"
        )
    label = _dsn_dbname(validation_dsn) or f"{model_name}-validation"
    return DbTarget(
        kind="postgres",
        target=validation_dsn,
        display=f"postgres-validation:{label}",
    )


def _create_postgres_dump_backup(
    target: DbTarget, reason: str, worktree_path: Path
) -> str:
    backup_dir = Path(worktree_path) / ".yoke" / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    safe_reason = _sanitize_backup_reason(reason)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    dest = backup_dir / f"postgres.{ts}.{safe_reason}.sql"
    timeout = runtime_settings.get_seconds(
        "backup_subprocess_timeout_seconds", 60,
    )
    result = subprocess.run(
        [
            "pg_dump",
            "--no-owner",
            "--no-privileges",
            "--file",
            str(dest),
            target.target,
        ],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0 or not dest.is_file():
        stderr = (result.stderr or "").strip()[-500:]
        raise RuntimeError(f"pg_dump backup failed: {stderr}")
    if dest.stat().st_size == 0:
        dest.unlink(missing_ok=True)
        raise RuntimeError("pg_dump backup file is empty")
    return str(dest)


def _sanitize_backup_reason(reason: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", reason.strip())
    cleaned = cleaned.strip("-._")
    return cleaned or "rollback"


def _dsn_dbname(dsn: str) -> Optional[str]:
    found: Optional[str] = None
    for part in dsn.split():
        if part.startswith("dbname="):
            found = part.split("=", 1)[1]
    return found


__all__ = [
    "DbTarget",
    "POSTGRES_VALIDATION_ENV_SUFFIX",
    "connect_db_target",
    "create_rollback_backup",
    "ensure_migration_audit_table_for_target",
    "fingerprint_db_target",
    "resolve_authoritative_db_target",
    "resolve_connection_env_var",
    "resolve_validation_db_target",
]
