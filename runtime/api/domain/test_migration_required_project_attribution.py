"""Explicit project writes survive removal of implicit database attribution."""

import importlib

import pytest

from yoke_core.domain.schema_common import _get_column_default

MIGRATION = importlib.import_module(
    "yoke_core.domain.migrations.0052_require_project_attribution"
)


def test_apply_preserves_attribution_and_omitted_writes_refuse(test_db):
    for table in MIGRATION.TABLES:
        test_db.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
        test_db.execute(
            f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL DEFAULT 1)"
        )
        test_db.execute(f"INSERT INTO {table} VALUES (1, 7)")
    MIGRATION.apply(test_db)
    MIGRATION.invariants(test_db)
    MIGRATION.apply(test_db)
    for table in MIGRATION.TABLES:
        assert (
            test_db.execute(f"SELECT project_id FROM {table} WHERE id=1").fetchone()[0]
            == 7
        )
        test_db.execute(f"INSERT INTO {table} VALUES (2, 8)")
        test_db.execute("SAVEPOINT missing_project")
        with pytest.raises(Exception):
            test_db.execute(f"INSERT INTO {table} (id) VALUES (3)")
        test_db.execute("ROLLBACK TO SAVEPOINT missing_project")
        assert test_db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 2


def test_default_removal_rolls_back_atomically(test_db):
    for table in MIGRATION.TABLES:
        test_db.execute(f"ALTER TABLE {table} ALTER COLUMN project_id SET DEFAULT 1")
    test_db.execute("SAVEPOINT attribution_cutover")
    MIGRATION.apply(test_db)
    MIGRATION.invariants(test_db)
    test_db.execute("ROLLBACK TO SAVEPOINT attribution_cutover")
    for table in MIGRATION.TABLES:
        assert _get_column_default(test_db, table, "project_id") is not None
    with pytest.raises(AssertionError, match="project_attribution_default_remains"):
        MIGRATION.invariants(test_db)


def test_new_universe_has_no_implicit_project_defaults(tmp_path):
    from runtime.api.fixtures.file_test_db import init_test_db, connect_test_db

    with init_test_db(tmp_path) as binding:
        conn = connect_test_db(binding)
        try:
            MIGRATION.invariants(conn)
        finally:
            conn.close()
