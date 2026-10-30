"""Nonblocking boot convergence of the event retention indexes.

Universe prune reads each severity's expired events as one index range
(``severity = S AND created_at < cutoff ORDER BY created_at``). Without this
index a nearly clean, large events table is scanned whole for its last rows.

The build follows ``events_function_index``: concurrent DDL on a separate
autocommit connection, serialized by an advisory lock, so event writers keep
inserting. Governed migrations record these builds in the ledger; catalog checks prove
their definitions, so no audit receipt is kept.
"""

from __future__ import annotations

from typing import Any

from psycopg.conninfo import make_conninfo
from yoke_contracts.refusal_recovery import compose_refusal
from yoke_contracts.schema_authority import refuse_without_serving_build_authority

from yoke_core.domain import administered_postgres, db_backend

RETENTION_INDEX_NAME = "idx_events_severity_created"
RETENTION_INDEX_COLUMNS = ("severity", "created_at")
NAME_RETENTION_INDEX_NAME = "idx_events_name_created"
RETENTION_INDEX_SPECS = (
    (RETENTION_INDEX_NAME, RETENTION_INDEX_COLUMNS),
    (NAME_RETENTION_INDEX_NAME, ("event_name", "created_at")),
)


def _index_state(conn: Any, name: str):
    return conn.execute(
        """
        SELECT i.indisvalid, i.indisready, t.relname, i.indpred IS NULL,
               ARRAY(SELECT pg_get_indexdef(i.indexrelid, k, true)
                     FROM generate_series(1, i.indnatts) AS k ORDER BY k)
        FROM pg_index i JOIN pg_class idx ON idx.oid=i.indexrelid
        JOIN pg_class t ON t.oid=i.indrelid
        JOIN pg_namespace ns ON ns.oid=idx.relnamespace
        WHERE idx.relname=%s AND ns.nspname=current_schema()
        """,
        (name,),
    ).fetchone()


def _verify_definition(state, name, columns) -> None:
    if (
        state[2] != "events"
        or not state[3]
        or tuple(state[4]) != columns
    ):
        raise RuntimeError(
            compose_refusal(
                f"events_retention_index_definition_mismatch: {name} must index events({', '.join(columns)}).",
                recovery="drop the differently defined index and restart the server so boot rebuilds it.",
            )
        )


def verify_retention_index(conn: Any) -> None:
    """Fail closed on a missing, interrupted, or differently defined index."""
    for name, columns in RETENTION_INDEX_SPECS:
        state = _index_state(conn, name)
        if state is None or not state[0] or not state[1]:
            raise RuntimeError(
                compose_refusal(
                    f"events_retention_index_not_ready: {name} is missing or its concurrent build did not finish.",
                    recovery="restart the server; boot rebuilds it concurrently.",
                )
            )
        _verify_definition(state, name, columns)


def ensure_retention_index(conn: Any, *, remove_obsolete: bool = False) -> None:
    """Build retention indexes, without committing the caller's work.

    Concurrent DDL cannot run inside the caller's transaction, so a separate
    autocommit connection targets the caller's exact database. Event writers
    keep inserting while it builds.
    """
    if not db_backend.connection_is_postgres(conn):
        return
    refuse_without_serving_build_authority(
        "building the events retention indexes",
        administering_env=administered_postgres.administering_target(connection=conn),
    )
    # psycopg redacts info.dsn; reopening needs the private password too.
    dsn = make_conninfo(conn.info.dsn, password=conn.info.password)
    with db_backend.connect_psycopg(dsn, autocommit=True) as index_conn:
        for name, columns in RETENTION_INDEX_SPECS:
            # Serialize competing boots without locking event writers.
            index_conn.execute("SELECT pg_advisory_lock(hashtext(%s))", (name,))
            try:
                state = _index_state(index_conn, name)
                if state is not None:
                    _verify_definition(state, name, columns)
                if state is not None and (not state[0] or not state[1]):
                    # Retry only this catalog-confirmed, interrupted build.
                    index_conn.execute(f"DROP INDEX CONCURRENTLY {name}")
                    state = None
                if state is None:
                    index_conn.execute(
                        f"CREATE INDEX CONCURRENTLY {name} ON events "
                        f"({', '.join(columns)})"
                    )
            finally:
                index_conn.execute("SELECT pg_advisory_unlock(hashtext(%s))", (name,))
        verify_retention_index(index_conn)
        if remove_obsolete:
            # The composite's leading column serves every former name lookup.
            # Only the governed migration requests this destructive operation.
            index_conn.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_events_event_name")
