"""Database-specific PostgreSQL defaults owned by the Yoke application role."""

from __future__ import annotations

from typing import Any

from psycopg import sql

from yoke_core.domain import db_backend


# The relay's bounded poll is shorter than this guard. Two minutes preserves
# headroom for normal request cleanup while terminating a stranded transaction
# soon enough to bound lock blocking and vacuum horizon retention.
IDLE_IN_TRANSACTION_SESSION_TIMEOUT = "2min"


class ApplicationRoleSettingsError(RuntimeError):
    """A required PostgreSQL application-role default could not be declared."""


def converge_application_role_settings(conn: Any) -> None:
    """Declare the current role's database-specific transaction guard."""
    if not db_backend.connection_is_postgres(conn):
        return

    try:
        database = str(conn.execute("SELECT current_database()").fetchone()[0])
        conn.execute(
            sql.SQL(
                "ALTER ROLE CURRENT_USER IN DATABASE {} "
                "SET idle_in_transaction_session_timeout = {}"
            ).format(
                sql.Identifier(database),
                sql.Literal(IDLE_IN_TRANSACTION_SESSION_TIMEOUT),
            )
        )
    except Exception as exc:
        raise ApplicationRoleSettingsError(
            "application role setting convergence failed for "
            "idle_in_transaction_session_timeout; ensure the configured "
            "PostgreSQL role can alter its own database-specific defaults, "
            "then restart Yoke"
        ) from exc


__all__ = [
    "ApplicationRoleSettingsError",
    "IDLE_IN_TRANSACTION_SESSION_TIMEOUT",
    "converge_application_role_settings",
]
