"""Item scan predicates use each pin's names without per-item queries."""

import json

from runtime.api.fixtures import pg_testdb
from runtime.api.domain.test_workflow_status_membership import custom_runtime
from yoke_core.domain.workflow_status_queries import (
    completed_items_sql,
    terminal_items_sql,
)


def test_sql_membership_uses_custom_terminal_names():
    name = pg_testdb.create_test_database()
    with pg_testdb.drop_database_on_close(
        pg_testdb.connect_test_database(name), name
    ) as conn:
        runtime = custom_runtime()
        conn.execute(
            "CREATE TABLE workflow_versions (id integer, definition_json text)"
        )
        conn.execute(
            "CREATE TABLE items (id integer, status text, workflow_version_id integer)"
        )
        conn.execute(
            "INSERT INTO workflow_versions VALUES (1,%s)",
            (json.dumps(runtime.definition),),
        )
        completed = runtime.completion_stage_id
        for item_id, status in enumerate((completed, "done", "cancelled"), start=1):
            conn.execute("INSERT INTO items VALUES (%s,%s,1)", (item_id, status))
        successful = conn.execute(
            f"SELECT i.id FROM items i WHERE {completed_items_sql(conn)} ORDER BY i.id"
        ).fetchall()
        terminal = conn.execute(
            f"SELECT i.id FROM items i WHERE {terminal_items_sql(conn)} ORDER BY i.id"
        ).fetchall()
        assert [row[0] for row in successful] == [1]
        assert [row[0] for row in terminal] == [1, 3]
