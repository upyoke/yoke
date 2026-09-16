"""The required-coverage refusal hands back a recipe that runs.

An item with no claim is told to register one, and the command it is told
to run names the item by its public reference — the thing the CLI accepts.
The fixture therefore carries the identity rows the refusal reads, with a
project sequence it can actually resolve.
"""

from __future__ import annotations

from yoke_core.domain.path_claim_required_gate import evaluate_required_coverage


def test_claim_required_gate_embeds_register_command() -> None:
    from runtime.api.fixtures.pg_testdb import (
        connect_test_database,
        create_test_database,
        drop_test_database,
    )
    from runtime.api.fixtures.schema_ddl import apply_fixture_ddl

    db_name = create_test_database()
    conn = connect_test_database(db_name)
    try:
        # The refusal names the item by reference, so the fixture carries
        # the identity the renderer reads.
        apply_fixture_ddl(
            conn,
            "CREATE TABLE path_claims (id INTEGER PRIMARY KEY, "
            "owner_kind TEXT, owner_item_id INTEGER, state TEXT, mode TEXT, "
            "exception_reason TEXT);"
            "CREATE TABLE path_claim_targets ("
            "claim_id INTEGER, target_id INTEGER);"
            "CREATE TABLE projects (id INTEGER PRIMARY KEY, slug TEXT, "
            "public_item_prefix TEXT);"
            "CREATE TABLE items (id INTEGER PRIMARY KEY, "
            "project_id INTEGER, project_sequence INTEGER);"
            "INSERT INTO projects (id, slug, public_item_prefix) "
            "VALUES (1, 'yoke', 'YOK');"
            "INSERT INTO items (id, project_id, project_sequence) "
            "VALUES (123, 1, 123);",
        )
        result = evaluate_required_coverage(conn, 123)
    finally:
        conn.close()
        drop_test_database(db_name)
    assert result["verdict"] == "block"
    reason = str(result["reason"])
    assert (
        "yoke claims path register "
        "--item YOK-123 --integration-target main "
        '--paths "<comma-separated paths>"'
    ) in reason
    assert (
        "yoke claims path register --item YOK-123 --mode exception --exception-reason"
    ) in reason
    assert "service_client" not in reason
