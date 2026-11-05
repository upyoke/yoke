# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import hashlib

from pathlib import Path

from psycopg import Error, sql

from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db

from yoke_core.domain import deployment_runs_schema, schema, schema_common_postgres

from yoke_core.domain.migration_restore_point import RESTORE_POINT_ENV

from yoke_core.domain.schema_common import _get_columns, _get_indexes, _get_tables

from yoke_core.domain.schema_init import converge_core_schema

def _apply_complete_control_plane_schema() -> None:
    schema.cmd_init()
    deployment_runs_schema.cmd_init()

def _column_map(conn) -> dict[str, frozenset[str]]:
    return {table: frozenset(_get_columns(conn, table)) for table in _get_tables(conn)}

def _record_boot_column_lookups(conn, monkeypatch) -> set[tuple[str, str]]:
    columns: set[tuple[str, str]] = set()
    original = schema_common_postgres._postgres_column_row

    def record(connection, table: str, column: str):
        columns.add((table, column))
        return original(connection, table, column)

    with monkeypatch.context() as patcher:
        patcher.setattr(schema_common_postgres, "_postgres_column_row", record)
        converge_core_schema(conn)
    return columns
