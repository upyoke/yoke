"""Unreadable File Budget pins do not poison caller transactions."""

from runtime.api.fixtures.pg_testdb import (
    connect_test_database,
    create_test_database,
    drop_test_database,
)
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from yoke_core.domain.file_budget_required_gate import evaluate


def test_legacy_schema_skips_but_invalid_complete_pin_blocks_cleanly():
    db_name = create_test_database()
    conn = connect_test_database(db_name)
    try:
        apply_fixture_ddl(
            conn,
            "CREATE TABLE items ("
            "id INTEGER PRIMARY KEY, workflow_id TEXT, "
            "workflow_version_id INTEGER, workflow_posture TEXT);"
            "INSERT INTO items VALUES (7, 'missing', 9, '{}');",
        )

        legacy = evaluate(conn, 7)

        assert legacy["verdict"] == "pass"
        assert conn.execute("SELECT 1").fetchone()[0] == 1
        apply_fixture_ddl(
            conn,
            "CREATE TABLE workflow_versions ("
            "id INTEGER PRIMARY KEY, workflow_id TEXT, version INTEGER, "
            "definition_json TEXT, definition_digest TEXT);",
        )
        blocked = evaluate(conn, 7)
        assert blocked["verdict"] == "block"
        assert "unreadable pinned File Budget policy" in blocked["reason"]
        assert conn.execute("SELECT 1").fetchone()[0] == 1
    finally:
        conn.close()
        drop_test_database(db_name)
