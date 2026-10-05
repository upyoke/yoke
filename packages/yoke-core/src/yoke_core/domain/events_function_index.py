"""Nonblocking, auditable boot convergence of the event function lookup index."""

from __future__ import annotations

from typing import Any
from psycopg.conninfo import make_conninfo

from yoke_contracts.control_plane_locality import local_authority_exempt
from yoke_contracts.schema_authority import refuse_without_serving_build_authority
from yoke_core.domain import administered_postgres, db_backend
from yoke_core.domain.migration_harness_audit import record_audit_fingerprint
from yoke_core.domain.sql_json import json_text_expr

FUNCTION_INDEX_NAME = "idx_events_function_identity"
FUNCTION_LOOKUP_CHARS = 64


def function_identity_sql(column: str = "envelope") -> str:
    """The decoded identifier shared by index creation and candidate selection."""
    return f"({json_text_expr(column)} #>> '{{context,function}}')"


def function_lookup_sql(column: str = "envelope") -> str:
    """Bound B-tree keys even for oversized unrelated historical identifiers."""
    return f"left({function_identity_sql(column)}, {FUNCTION_LOOKUP_CHARS})"


def _connection_dsn(conn: Any) -> str:
    # psycopg deliberately redacts info.dsn. Reopening the same connection
    # needs its actual credential; retain it only in this private value.
    return make_conninfo(conn.info.dsn, password=conn.info.password)


def _index_state(conn: Any):
    return conn.execute(
        """
        SELECT i.indisvalid, i.indisready, t.relname, op.opcname,
               pg_get_expr(i.indpred, i.indrelid), pg_get_expr(i.indexprs, i.indrelid)
        FROM pg_index i JOIN pg_class idx ON idx.oid=i.indexrelid
        JOIN pg_class t ON t.oid=i.indrelid
        JOIN pg_namespace ns ON ns.oid=idx.relnamespace
        JOIN pg_opclass op ON op.oid=i.indclass[0]
        WHERE idx.relname=%s AND ns.nspname=current_schema()
        """,
        (FUNCTION_INDEX_NAME,),
    ).fetchone()


def _verify_definition(state) -> None:
    if (
        state[2] != "events"
        or state[3] != "text_pattern_ops"
        or state[4] != "(event_name = 'YokeFunctionCalled'::text)"
        or "'{context,function}'::text[]" not in (state[5] or "")
        or not state[5].startswith('"left"(')
        or not state[5].endswith(f", {FUNCTION_LOOKUP_CHARS})")
    ):
        raise RuntimeError("events_function_index_definition_mismatch")


def verify_function_index(conn: Any) -> None:
    """Fail closed on a missing, interrupted, or differently owned index."""
    state = _index_state(conn)
    if state is None or not state[0] or not state[1]:
        raise RuntimeError("events_function_index_not_ready")
    _verify_definition(state)


def ensure_function_index(conn: Any) -> None:
    """Build only this additive index, without committing the caller's work.

    Concurrent DDL cannot share the transactional history connection. The
    explicit connection targets that caller's database, never an ambient DB.
    The documented audit exception covers its independently committed catalog
    change; ordered history still verifies it before recording membership.
    """
    if not db_backend.connection_is_postgres(conn):
        return
    refuse_without_serving_build_authority(
        "building the events function index",
        administering_env=administered_postgres.administering_target(connection=conn),
    )
    dsn = _connection_dsn(conn)
    with db_backend.connect_psycopg(dsn, autocommit=True) as index_conn:
        # Serialize competing boots, without locking event writers. The lock
        # identity derives from the index's canonical name.
        index_conn.execute(
            "SELECT pg_advisory_lock(hashtext(%s))", (FUNCTION_INDEX_NAME,)
        )
        try:
            state = _index_state(index_conn)
            if state is not None:
                _verify_definition(state)
            if state is not None and not state[0]:
                # A cancelled concurrent build leaves an invalid index. Only
                # our named, catalog-confirmed index is eligible for retry.
                index_conn.execute(f"DROP INDEX CONCURRENTLY {FUNCTION_INDEX_NAME}")
                state = None
            if state is None:
                index_conn.execute(
                    f"CREATE INDEX CONCURRENTLY {FUNCTION_INDEX_NAME} ON events "
                    f"({function_lookup_sql()} text_pattern_ops) "
                    "WHERE event_name='YokeFunctionCalled'"
                )
            verify_function_index(index_conn)
            recorded = index_conn.execute(
                "SELECT 1 FROM migration_audit WHERE migration_name=%s "
                "AND state='completed' LIMIT 1",
                ("events-function-index",),
            ).fetchone()
            if recorded is None:
                with db_backend.bound_pg_dsn(dsn), local_authority_exempt():
                    record_audit_fingerprint(
                        db_path=dsn,
                        name="events-function-index",
                        description=f"Concurrent additive index validated: {FUNCTION_INDEX_NAME}",
                        tables=[],
                        pre_counts={},
                        post_counts={},
                        backup_reason=None,
                        exception_reason="events-function-index: additive catalog only; no rows rewritten",
                    )
        finally:
            index_conn.execute(
                "SELECT pg_advisory_unlock(hashtext(%s))", (FUNCTION_INDEX_NAME,)
            )
