"""Store SQL NULL when session model facts resolve to no execution level."""

from yoke_contracts.refusal_recovery import compose_refusal
from yoke_core.domain.db_backend import connection_is_postgres


# Older servers stamp the retired value on registration and model refresh.
MINIMUM_SERVING_VERSION = "next-release"


def _column(conn):
    return conn.execute(
        "SELECT is_nullable, column_default FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = 'harness_sessions' "
        "AND column_name = 'execution_level'"
    ).fetchone()


def apply(conn):
    if not connection_is_postgres(conn):
        return
    column = _column(conn)
    if column is not None and (column[0] != "YES" or column[1] is not None):
        conn.execute(
            "ALTER TABLE harness_sessions "
            "ALTER COLUMN execution_level DROP NOT NULL, "
            "ALTER COLUMN execution_level DROP DEFAULT"
        )
    conn.execute(
        "UPDATE harness_sessions SET execution_level = NULL WHERE execution_level = 'primary'"
    )


def invariants(conn):
    if not connection_is_postgres(conn):
        return
    column = _column(conn)
    if column is None or column[0] != "YES" or column[1] is not None:
        raise AssertionError(
            compose_refusal(
                "harness_sessions.execution_level must be nullable without a default.",
                recovery="Rehearse and rerun migration 0124_nullable_session_execution_level.",
            )
        )
    remaining = conn.execute(
        "SELECT 1 FROM harness_sessions WHERE execution_level = 'primary' LIMIT 1"
    ).fetchone()
    if remaining is not None:
        raise AssertionError(
            compose_refusal(
                "harness_sessions.execution_level still holds the retired placeholder.",
                recovery="Rehearse and rerun migration 0124_nullable_session_execution_level.",
            )
        )
