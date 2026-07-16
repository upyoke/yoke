"""Focused tests for the ``db.read.run`` diagnostic read handler."""

from __future__ import annotations

from runtime.api.fixtures import pg_testdb
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import json_helper
from yoke_core.domain.handlers import db_read
from yoke_core.domain.handlers.db_read import DbReadRunRequest
from yoke_core.domain.handlers.db_read_sql import validate_read_only_sql


def _refusal_code(sql: str) -> str | None:
    refusal = validate_read_only_sql(sql)
    return None if refusal is None else refusal.code


def test_sql_guard_allows_select_explain_and_read_only_with() -> None:
    assert _refusal_code("SELECT ';' AS semi;") is None
    assert _refusal_code("-- hi\nEXPLAIN SELECT * FROM items") is None
    assert _refusal_code("WITH rows AS (SELECT 1 AS id) SELECT id FROM rows") is None


def test_sql_guard_refuses_writes_ddl_and_multiple_statements() -> None:
    assert _refusal_code("SELECT 1; SELECT 2") == "sql_multiple_statements"
    assert _refusal_code("UPDATE items SET title = 'x'") == "sql_write_refused"
    assert _refusal_code("SELECT * INTO scratch FROM items") == "sql_ddl_refused"
    assert _refusal_code("EXPLAIN UPDATE items SET title = 'x'") == "sql_write_refused"
    assert (
        _refusal_code("WITH moved AS (DELETE FROM items RETURNING *) SELECT * FROM moved")
        == "sql_write_refused"
    )
    assert _refusal_code("CREATE TABLE scratch (id int)") == "sql_ddl_refused"


def test_runner_returns_columns_rows_and_truncation() -> None:
    with pg_testdb.test_database() as conn:
        conn.execute("CREATE TABLE sample (id INTEGER, title TEXT)")
        for row in [(1, "one"), (2, "two"), (3, "three")]:
            conn.execute("INSERT INTO sample (id, title) VALUES (%s, %s)", row)
        conn.commit()

        result = db_read.run_db_read(
            DbReadRunRequest(
                sql="SELECT id, title FROM sample ORDER BY id", row_cap=2,
            )
        )

    assert result.columns == ["id", "title"]
    assert result.rows == [[1, "one"], [2, "two"]]
    assert result.row_count == 2
    assert result.truncated is True


def test_runner_redacts_sensitive_settings_even_when_column_is_aliased() -> None:
    settings = json_helper.dumps_compact({
        "database": {"name": "example_prod"},
        "pulumi": {
            "encrypted_key": "opaque-ciphertext",
            "secrets_provider": "provider-reference",
        },
        "github_app": {
            "private_key_secret_arn": "secret-resource-reference",
        },
    })
    with pg_testdb.test_database() as conn:
        conn.execute(
            "CREATE TABLE diagnostic_settings "
            "(settings TEXT, encrypted_key TEXT, branch TEXT)"
        )
        conn.execute(
            "INSERT INTO diagnostic_settings "
            "(settings, encrypted_key, branch) VALUES (%s, %s, %s)",
            (settings, "direct-ciphertext", "main"),
        )
        conn.commit()

        result = db_read.run_db_read(DbReadRunRequest(sql=(
            "SELECT settings AS config, encrypted_key, branch "
            "FROM diagnostic_settings"
        )))

    redacted = json_helper.loads_text(result.rows[0][0])
    assert redacted["database"]["name"] == "example_prod"
    assert redacted["pulumi"]["encrypted_key"] == "<redacted>"
    assert redacted["pulumi"]["secrets_provider"] == "<redacted>"
    assert redacted["github_app"]["private_key_secret_arn"] == "<redacted>"
    assert result.rows[0][1:] == ["<redacted>", "main"]


def test_handler_returns_typed_refusal_for_mutation() -> None:
    outcome = db_read.handle_db_read(
        FunctionCallRequest(
            function=db_read.DB_READ_FUNCTION_ID,
            actor=ActorContext(actor_id="1", session_id=""),
            target=TargetRef(kind="global"),
            payload={"sql": "SELECT * FROM items; DROP TABLE items"},
        )
    )

    assert not outcome.primary_success
    assert outcome.error is not None
    assert outcome.error.code == "sql_multiple_statements"


def test_missing_column_error_includes_live_columns_and_packet_note() -> None:
    # The fixture schema's ouroboros_entries carries category/body and no
    # kind column, so the missing-column teaching path fires as-is.
    with pg_testdb.test_database():
        outcome = db_read.handle_db_read(
            FunctionCallRequest(
                function=db_read.DB_READ_FUNCTION_ID,
                actor=ActorContext(actor_id="1", session_id=""),
                target=TargetRef(kind="global"),
                payload={"sql": "SELECT kind FROM ouroboros_entries"},
            )
        )

    assert not outcome.primary_success
    assert outcome.error is not None
    assert outcome.error.code == "sql_execution_failed"
    assert "Live columns for ouroboros_entries" in outcome.error.message
    assert "category text" in outcome.error.message
    assert "body text" in outcome.error.message
    assert "there are NO `kind` or `evidence` columns" in outcome.error.message


def test_deployment_runs_missing_item_id_teaches_junction_table() -> None:
    # The fixture schema's deployment_runs has no item_id column, so the
    # junction-table teaching path fires as-is.
    with pg_testdb.test_database():
        outcome = db_read.handle_db_read(
            FunctionCallRequest(
                function=db_read.DB_READ_FUNCTION_ID,
                actor=ActorContext(actor_id="1", session_id=""),
                target=TargetRef(kind="global"),
                payload={"sql": "SELECT item_id FROM deployment_runs"},
            )
        )

    assert not outcome.primary_success
    assert outcome.error is not None
    assert "Live columns for deployment_runs" in outcome.error.message
    assert "deployment_runs.id" in outcome.error.message
    assert "There is no `item_id` column on this table" in outcome.error.message
    assert "deployment_run_items" in outcome.error.message
