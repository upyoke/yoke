"""Backend-declared DB target helpers for governed migration apply."""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional

from yoke_core.domain import db_backend, db_helpers
from yoke_core.domain.migration_apply_contract import MigrationApplyError
from yoke_core.domain.migration_validation_binding import (
    binding_file,
    read_binding,
    validation_env_var,
)
from yoke_core.domain.postgres_dump_restore_point import (
    dump_postgres_to_directory,
)
from yoke_core.domain.schema_fingerprint import fingerprint_kind
from yoke_core.domain.worktree_validation_surface import (
    provision_validation_surfaces,
    resolve_validation_db_paths,
)
from yoke_contracts.migration_rehearsal_teaching import PREFLIGHT_HELP_COMMAND


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
    value = str(config.get("connection_env_var") or "").strip()
    if not value:
        raise MigrationApplyError(
            "runner.config.connection_env_var is required; generic migration "
            "routing cannot infer project database authority"
        )
    return value


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
        target = _resolve_postgres_authority(model)
        label = (
            _dsn_dbname(target)
            or ((auth.get("location") or {}).get("database_name"))
            or "authority"
        )
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
    authoritative_target: DbTarget,
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
        return _resolve_external_postgres_validation(
            model,
            model_name,
            authoritative_target,
        )
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
        with db_backend.bound_pg_dsn(target.target):
            return db_backend.connect()
    raise MigrationApplyError(
        f"database target kind {target.kind!r} is not connectable"
    )


def _database_target_identity(target: DbTarget) -> tuple[str, ...]:
    """Return a credential-free identity for one concrete database target."""

    if target.kind == "sqlite_file":
        return (target.kind, str(Path(target.target).resolve()))
    if target.kind != "postgres":
        raise MigrationApplyError(
            f"database target kind {target.kind!r} has no identity verifier"
        )
    conn = connect_db_target(target)
    try:
        row = conn.execute(
            "SELECT current_database() AS database_name, "
            "system_identifier::text AS system_identifier "
            "FROM pg_control_system()"
        ).fetchone()
    except Exception as exc:  # noqa: BLE001 - redact connection details
        raise MigrationApplyError(
            f"could not verify database identity for {target.display}: "
            f"{type(exc).__name__}"
        ) from exc
    finally:
        conn.close()
    if row is None:
        raise MigrationApplyError(
            f"database identity query returned no row for {target.display}"
        )
    if hasattr(row, "keys"):
        return (
            target.kind,
            str(row["system_identifier"]),
            str(row["database_name"]),
        )
    return (target.kind, str(row[1]), str(row[0]))


def assert_distinct_database_targets(
    authoritative: DbTarget, validation: DbTarget
) -> None:
    """Refuse when two bindings reach the same physical database."""

    if _database_target_identity(authoritative) == _database_target_identity(
        validation
    ):
        raise MigrationApplyError(
            "validation database identity matches the authoritative database; "
            "refusing to rehearse"
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
        worktree_path,
        project,
        db_path=control_db_path,
    )
    failure = next((s for s in provision.surfaces if s.error), None)
    if failure is not None:
        raise MigrationApplyError(
            f"validation surface provisioning failed for model "
            f"'{failure.model_name}': {failure.error}"
        )
    validation_paths = resolve_validation_db_paths(
        worktree_path,
        project,
        db_path=control_db_path,
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
    model: Mapping[str, Any],
    model_name: str,
    authoritative_target: DbTarget,
) -> DbTarget:
    if authoritative_target.kind != "postgres":
        raise MigrationApplyError(
            f"model '{model_name}' uses external_validation but its "
            "authoritative database is not Postgres"
        )
    env_var = validation_env_var(resolve_connection_env_var(model))
    validation_dsn = read_binding(env_var)
    if not validation_dsn:
        raise MigrationApplyError(
            f"model '{model_name}' uses external_validation; rehearsal needs a "
            "separate disposable Postgres database bound as "
            f"{env_var} — exported, or written to {binding_file(env_var)}. The "
            "authoritative Postgres DSN is never used as the rehearsal target. "
            f"`{PREFLIGHT_HELP_COMMAND}` carries the provisioning recipe."
        )
    if validation_dsn == authoritative_target.target:
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


def _resolve_postgres_authority(model: Mapping[str, Any]) -> str:
    env_var = resolve_connection_env_var(model)
    if env_var == db_backend.PG_DSN_ENV:
        try:
            return db_backend.resolve_pg_dsn()
        except Exception as exc:  # noqa: BLE001
            raise MigrationApplyError(
                "authoritative_db.kind 'postgres' requires a resolved "
                f"Postgres DSN from {db_backend.PG_DSN_ENV}, "
                f"{db_backend.PG_DSN_FILE_ENV}, managed credentials, or "
                "connected-env credentials"
            ) from exc
    target = os.environ.get(env_var, "").strip()
    if not target:
        raise MigrationApplyError(
            "authoritative_db.kind 'postgres' requires the model-declared "
            f"{env_var} environment variable; custom model routing never "
            f"falls back to ambient {db_backend.PG_DSN_ENV} authority"
        )
    return target


def _create_postgres_dump_backup(
    target: DbTarget, reason: str, worktree_path: Path
) -> str:
    return dump_postgres_to_directory(
        target.target, reason, Path(worktree_path) / ".yoke" / "backups"
    )


def _dsn_dbname(dsn: str) -> Optional[str]:
    found: Optional[str] = None
    for part in dsn.split():
        if part.startswith("dbname="):
            found = part.split("=", 1)[1]
    return found


__all__ = [
    "DbTarget",
    "assert_distinct_database_targets",
    "connect_db_target",
    "create_rollback_backup",
    "dump_postgres_to_directory",
    "ensure_migration_audit_table_for_target",
    "fingerprint_db_target",
    "resolve_authoritative_db_target",
    "resolve_connection_env_var",
    "resolve_validation_db_target",
]
