"""Persist the build observed by environment QA executions and results."""

from yoke_core.domain.schema_common import _column_exists


def apply(conn):
    for table in ("qa_runs", "qa_plan_executions"):
        for column in ("served_build_sha", "served_build_status"):
            if not _column_exists(conn, table, column):
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} TEXT")


def invariants(conn):
    for table in ("qa_runs", "qa_plan_executions"):
        for column in ("served_build_sha", "served_build_status"):
            assert _column_exists(conn, table, column), f"{table}.{column} missing"
