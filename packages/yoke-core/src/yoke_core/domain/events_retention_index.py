"""Nonblocking, auditable boot convergence of the event retention index.

Universe prune reads each severity's expired events as one index range
(``severity = S AND created_at < cutoff ORDER BY created_at``). Without this
index a nearly clean, large events table is scanned whole for its last rows.
"""

from __future__ import annotations

from typing import Any

from psycopg.conninfo import make_conninfo

from yoke_contracts.control_plane_locality import local_authority_exempt
from yoke_contracts.schema_authority import refuse_without_serving_build_authority
from yoke_core.domain import administered_postgres, db_backend
from yoke_core.domain.migration_harness_audit import record_audit_fingerprint

RETENTION_INDEX_NAME = "idx_events_severity_created"
RETENTION_INDEX_COLUMNS = ("severity", "created_at")
BOOTSTRAP_AUDIT_RECORD = {
    "name": "events-retention-index",
    "description": f"Concurrent additive index validated: {RETENTION_INDEX_NAME}",
    "exception_reason": "events-retention-index: additive catalog only; no rows rewritten",
    "tables": [],
    "pre_counts": {},
    "post_counts": {},
    "backup_reason": None,
}


def _index_state(conn: Any):
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
        (RETENTION_INDEX_NAME,),
    ).fetchone()


def _verify_definition(state) -> None:
    if (
        state[2] != "events"
        or not state[3]
        or tuple(state[4]) != RETENTION_INDEX_COLUMNS
    ):
        raise RuntimeError(
            "events_retention_index_definition_mismatch: "
            f"{RETENTION_INDEX_NAME} must index events({', '.join(RETENTION_INDEX_COLUMNS)}). "
            "Recovery: drop the differently defined index and restart the server so boot rebuilds it."
        )


def verify_retention_index(conn: Any) -> None:
    """Fail closed on a missing, interrupted, or differently defined index."""
    state = _index_state(conn)
    if state is None or not state[0] or not state[1]:
        raise RuntimeError(
            "events_retention_index_not_ready: "
            f"{RETENTION_INDEX_NAME} is missing or its concurrent build did not finish. "
            "Recovery: restart the server; boot rebuilds it concurrently."
        )
    _verify_definition(state)


def ensure_retention_index(conn: Any) -> None:
    """Build only this additive index, without committing the caller's work.

    Concurrent DDL cannot run inside the caller's transaction, so a separate
    autocommit connection targets the caller's exact database. Event writers
    keep inserting while it builds.
    """
    if not db_backend.connection_is_postgres(conn):
        return
    refuse_without_serving_build_authority(
        "building the events retention index",
        administering_env=administered_postgres.administering_target(connection=conn),
    )
    # psycopg redacts info.dsn; reopening needs the private password too.
    dsn = make_conninfo(conn.info.dsn, password=conn.info.password)
    with db_backend.connect_psycopg(dsn, autocommit=True) as index_conn:
        # Serialize competing boots without locking event writers.
        index_conn.execute(
            "SELECT pg_advisory_lock(hashtext(%s))", (RETENTION_INDEX_NAME,)
        )
        try:
            state = _index_state(index_conn)
            if state is not None:
                _verify_definition(state)
            if state is not None and not state[0]:
                # A cancelled concurrent build leaves an invalid index; only
                # this named, catalog-confirmed index is dropped for retry.
                index_conn.execute(f"DROP INDEX CONCURRENTLY {RETENTION_INDEX_NAME}")
                state = None
            if state is None:
                index_conn.execute(
                    f"CREATE INDEX CONCURRENTLY {RETENTION_INDEX_NAME} ON events "
                    f"({', '.join(RETENTION_INDEX_COLUMNS)})"
                )
            verify_retention_index(index_conn)
            recorded = index_conn.execute(
                "SELECT 1 FROM migration_audit WHERE migration_name=%s "
                "AND state='completed' LIMIT 1",
                (BOOTSTRAP_AUDIT_RECORD["name"],),
            ).fetchone()
            if recorded is None:
                with db_backend.bound_pg_dsn(dsn), local_authority_exempt():
                    record_audit_fingerprint(
                        db_path=dsn,
                        **BOOTSTRAP_AUDIT_RECORD,
                    )
        finally:
            index_conn.execute(
                "SELECT pg_advisory_unlock(hashtext(%s))", (RETENTION_INDEX_NAME,)
            )
