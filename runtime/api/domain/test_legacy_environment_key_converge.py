"""Boot converge of a universe still on text environment keys.

Additive schema used to declare ``INTEGER REFERENCES environments(id)``
before the ordered history converted the live text primary key. That
mismatch failed the boot, so the numeric-key entry never ran. These tests
seed the prior shape and prove converge completes on integer keys.
"""

from __future__ import annotations

import psycopg
import pytest

from runtime.api.fixtures import pg_testdb
from yoke_core.domain.migration_restore_point import RESTORE_POINT_ENV
from yoke_core.domain.migrations._numeric_environment_site_keys import (
    registry_is_numeric,
)
from yoke_core.domain.schema_common import (
    _add_column_if_not_exists,
    environment_reference_column_sql,
)
from yoke_core.domain.schema_init import converge_core_schema


_STAMPED_BEFORE_NUMERIC_KEYS = (
    "0001_retire_superseded_surfaces",
    "0002_drop_migration_apply_stages",
    "0003_workflow_and_deployment_stage_vocabulary",
    "0004_backfill_serving_floors",
)


def _column_type(conn, table: str, column: str) -> str:
    row = conn.execute(
        "SELECT data_type FROM information_schema.columns "
        "WHERE table_schema = current_schema() "
        "AND table_name = %s AND column_name = %s",
        (table, column),
    ).fetchone()
    assert row is not None
    return str(row[0])


def _seed_text_environment_universe(conn) -> None:
    conn.execute(
        """
        CREATE TABLE organizations (
            id INTEGER PRIMARY KEY,
            slug TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            domain TEXT DEFAULT NULL,
            settings TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "INSERT INTO organizations (id, slug, name, created_at) "
        "VALUES (1, 'default', 'Default Org', '2026-01-01T00:00:00Z')"
    )
    conn.execute(
        """
        CREATE TABLE projects (
            id INTEGER PRIMARY KEY,
            slug TEXT NOT NULL,
            name TEXT NOT NULL,
            public_item_prefix TEXT NOT NULL DEFAULT 'YOK',
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "INSERT INTO projects (id, slug, name, created_at) "
        "VALUES (1, 'yoke', 'Yoke', '2026-01-01T00:00:00Z')"
    )
    conn.execute(
        """
        CREATE TABLE sites (
            id TEXT PRIMARY KEY,
            project_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            description TEXT,
            created_at TEXT NOT NULL,
            settings TEXT DEFAULT '{}'
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE environments (
            id TEXT PRIMARY KEY,
            site TEXT NOT NULL,
            name TEXT NOT NULL,
            url TEXT,
            deploy_method TEXT,
            deploy_command TEXT,
            health_check_url TEXT,
            config_notes TEXT,
            last_deployed_at TEXT,
            created_at TEXT NOT NULL,
            settings TEXT DEFAULT '{}'
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE deployment_flows (
            id TEXT PRIMARY KEY,
            project_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            stages TEXT NOT NULL,
            created_at TEXT NOT NULL,
            target_env TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE deployment_runs (
            id TEXT PRIMARY KEY,
            project_id INTEGER NOT NULL,
            flow TEXT,
            status TEXT NOT NULL DEFAULT 'created',
            current_stage TEXT,
            created_at TEXT NOT NULL,
            target_env TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE deployment_run_items (
            run_id TEXT NOT NULL,
            item_id INTEGER NOT NULL,
            added_at TEXT NOT NULL,
            PRIMARY KEY (run_id, item_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE deployment_run_qa (
            id INTEGER PRIMARY KEY,
            run_id TEXT NOT NULL,
            check_name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            updated_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE applied_migrations (
            migration_name TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL,
            applied_by TEXT,
            minimum_serving_version TEXT,
            content_sha256 TEXT
        )
        """
    )
    for name in _STAMPED_BEFORE_NUMERIC_KEYS:
        conn.execute(
            "INSERT INTO applied_migrations "
            "(migration_name, applied_at, applied_by) "
            "VALUES (%s, '2026-01-01T00:00:00Z', 'test')",
            (name,),
        )
    conn.commit()


def test_environment_reference_sql_matches_live_text_primary_key() -> None:
    database = pg_testdb.create_test_database(pooled=False)
    try:
        dsn = pg_testdb.dsn_for_test_database(database)
        with psycopg.connect(dsn) as conn:
            conn.execute("CREATE TABLE environments (id TEXT PRIMARY KEY, name TEXT)")
            conn.commit()
            assert (
                environment_reference_column_sql(conn)
                == "TEXT REFERENCES environments(id)"
            )
    finally:
        pg_testdb.drop_test_database(database, pooled=False)


def test_environment_reference_sql_matches_live_integer_primary_key() -> None:
    database = pg_testdb.create_test_database(pooled=False)
    try:
        dsn = pg_testdb.dsn_for_test_database(database)
        with psycopg.connect(dsn) as conn:
            conn.execute(
                "CREATE TABLE environments (id INTEGER PRIMARY KEY, name TEXT)"
            )
            conn.commit()
            assert (
                environment_reference_column_sql(conn)
                == "INTEGER REFERENCES environments(id)"
            )
    finally:
        pg_testdb.drop_test_database(database, pooled=False)


def test_additive_schema_accepts_text_environment_keys() -> None:
    database = pg_testdb.create_test_database(pooled=False)
    try:
        dsn = pg_testdb.dsn_for_test_database(database)
        with psycopg.connect(dsn) as conn:
            _seed_text_environment_universe(conn)
            environment_ref = environment_reference_column_sql(conn)
            _add_column_if_not_exists(
                conn,
                "deployment_flows",
                "target_environment_id",
                environment_ref,
            )
            _add_column_if_not_exists(
                conn,
                "deployment_runs",
                "target_environment_id",
                environment_ref,
            )
            conn.commit()
            assert (
                _column_type(conn, "deployment_flows", "target_environment_id")
                == "text"
            )
            assert (
                _column_type(conn, "deployment_runs", "target_environment_id") == "text"
            )
            fk = conn.execute(
                "SELECT 1 FROM pg_constraint "
                "WHERE conname = "
                "'deployment_flows_target_environment_id_fkey'"
            ).fetchone()
            assert fk is not None
    finally:
        pg_testdb.drop_test_database(database, pooled=False)


def test_fresh_universe_converge_uses_integer_environment_keys() -> None:
    database = pg_testdb.create_test_database(pooled=False)
    try:
        dsn = pg_testdb.dsn_for_test_database(database)
        with psycopg.connect(dsn) as conn:
            converge_core_schema(conn)
            conn.commit()
            assert registry_is_numeric(conn)
            assert _column_type(conn, "environments", "id") == "integer"
            assert (
                _column_type(conn, "deployment_flows", "target_environment_id")
                == "integer"
            )
    finally:
        pg_testdb.drop_test_database(database, pooled=False)


def test_converge_converts_legacy_text_environment_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(RESTORE_POINT_ENV, "snapshot:legacy-text-env-keys")
    database = pg_testdb.create_test_database(pooled=False)
    try:
        dsn = pg_testdb.dsn_for_test_database(database)
        with psycopg.connect(dsn) as conn:
            _seed_text_environment_universe(conn)
            assert _column_type(conn, "environments", "id") == "text"
            converge_core_schema(conn)
            conn.commit()
            assert registry_is_numeric(conn)
            assert _column_type(conn, "environments", "id") == "integer"
            assert _column_type(conn, "sites", "id") == "integer"
            applied = conn.execute(
                "SELECT 1 FROM applied_migrations "
                "WHERE migration_name = '0010_numeric_environment_site_keys'"
            ).fetchone()
            assert applied is not None
            fk = conn.execute(
                "SELECT 1 FROM pg_constraint "
                "WHERE conname = "
                "'deployment_flows_target_environment_id_fkey'"
            ).fetchone()
            assert fk is not None
            assert (
                _column_type(conn, "deployment_flows", "target_environment_id")
                == "integer"
            )
    finally:
        pg_testdb.drop_test_database(database, pooled=False)
