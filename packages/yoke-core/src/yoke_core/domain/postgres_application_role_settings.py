"""Database-specific PostgreSQL defaults owned by the Yoke application role."""

from __future__ import annotations

import sys
from typing import Any

from psycopg import sql

from yoke_core.domain import db_backend


# The relay's bounded poll is shorter than this guard. Two minutes preserves
# headroom for normal request cleanup while terminating a stranded transaction
# soon enough to bound lock blocking and vacuum horizon retention.
IDLE_IN_TRANSACTION_SESSION_TIMEOUT = "2min"

APPLICATION_ROLE_DEFAULT_NOT_PERSISTED = "application_role_default_not_persisted"
APPLICATION_ROLE_DEFAULT_RECOVERY = (
    "the next boot retries; if it never persists, grant the PostgreSQL role "
    "permission to ALTER its own database-specific defaults, or connect as a "
    "role that can"
)

_SETTING_NAME = "idle_in_transaction_session_timeout"


class ApplicationRoleSettingsError(RuntimeError):
    """A required PostgreSQL application-role default could not be declared."""


def _role_default_already_persisted(conn: Any, database: str) -> bool:
    """Report whether the role already carries the desired database default.

    Reading before writing is what keeps concurrent boots off the shared
    ``pg_db_role_setting`` catalog row: ``ALTER ROLE`` updates that row in
    place, and two processes doing it at once raise ``tuple concurrently
    updated``. After the first boot the value is already right, so the steady
    state performs no catalog write at all.
    """
    row = conn.execute(
        "SELECT s.setconfig FROM pg_db_role_setting s "
        "JOIN pg_roles r ON r.oid = s.setrole "
        "JOIN pg_database d ON d.oid = s.setdatabase "
        "WHERE r.rolname = CURRENT_USER AND d.datname = %s",
        (database,),
    ).fetchone()
    if not row:
        return False
    setconfig = list(row[0] or [])
    return f"{_SETTING_NAME}={IDLE_IN_TRANSACTION_SESSION_TIMEOUT}" in setconfig


def _persist_role_default(conn: Any, database: str) -> None:
    """Record the guard as the role's default for *database*, best-effort.

    Persisting must never fail the boot: the role default only governs future
    sessions, and this session gets the guard from the ``SET`` that follows.
    Raising here would make every later read of the universe refuse over a
    durability detail — the exact outage this degradation exists to prevent.
    """
    if _role_default_already_persisted(conn, database):
        return
    try:
        conn.execute(
            sql.SQL("ALTER ROLE CURRENT_USER IN DATABASE {} SET {} = {}").format(
                sql.Identifier(database),
                sql.Identifier(_SETTING_NAME),
                sql.Literal(IDLE_IN_TRANSACTION_SESSION_TIMEOUT),
            )
        )
    except Exception as exc:
        # A failed catalog statement poisons the transaction, and every later
        # converge step would then refuse. This runs first in the convergence,
        # before any DDL, so the rollback discards nothing else.
        conn.rollback()
        sys.stderr.write(
            f"{APPLICATION_ROLE_DEFAULT_NOT_PERSISTED}: could not record "
            f"{_SETTING_NAME}={IDLE_IN_TRANSACTION_SESSION_TIMEOUT} as the "
            f"role default for database {database} ({exc}). This session is "
            f"still guarded. Recover: {APPLICATION_ROLE_DEFAULT_RECOVERY}.\n"
        )


def converge_application_role_settings(conn: Any) -> None:
    """Declare this session's transaction guard and the role default behind it.

    Runs first in :func:`yoke_core.domain.schema_init.converge_core_schema`,
    before any DDL. The session ``SET`` is required and fails loudly; recording
    the same value as the role's database default is best-effort, so neither a
    role that cannot alter its own defaults nor a concurrent boot racing on the
    catalog row can stop the universe from serving.
    """
    if not db_backend.connection_is_postgres(conn):
        return

    database = str(conn.execute("SELECT current_database()").fetchone()[0])
    _persist_role_default(conn, database)

    try:
        conn.execute(
            sql.SQL("SET {} = {}").format(
                sql.Identifier(_SETTING_NAME),
                sql.Literal(IDLE_IN_TRANSACTION_SESSION_TIMEOUT),
            )
        )
    except Exception as exc:
        raise ApplicationRoleSettingsError(
            "application role setting convergence failed for "
            f"{_SETTING_NAME}; ensure the configured PostgreSQL role can SET "
            f"{_SETTING_NAME}, then restart Yoke"
        ) from exc


__all__ = [
    "APPLICATION_ROLE_DEFAULT_NOT_PERSISTED",
    "APPLICATION_ROLE_DEFAULT_RECOVERY",
    "ApplicationRoleSettingsError",
    "IDLE_IN_TRANSACTION_SESSION_TIMEOUT",
    "converge_application_role_settings",
]
