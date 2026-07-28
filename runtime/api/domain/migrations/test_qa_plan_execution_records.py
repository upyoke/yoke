"""Governed migration coverage for durable QA plan execution records."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3

from runtime.api.domain.migrations import (
    qa_plan_execution_records as source_wrapper,
)
from runtime.api.fixtures.backlog_inserts import (
    insert_item,
    insert_qa_requirement,
)
from yoke_core.domain.migration_apply_manifest import validate_manifest_payload
from yoke_core.domain.migrations.qa_plan_execution_records import (
    MIGRATION_NAME,
    apply,
    invariants,
)
from yoke_core.domain.qa_plan_execution_schema import (
    QA_PLAN_EXECUTION_COLUMNS,
    QA_PLAN_EXECUTION_INDEXES,
    QA_PLAN_EXECUTION_RESULT_COLUMNS,
    QA_PLAN_EXECUTION_RESULT_TABLE,
    QA_PLAN_EXECUTION_TABLE,
)
from yoke_core.domain.schema_common import (
    _get_check_constraint_defs,
    _get_columns_with_types,
    _get_indexes,
    _get_tables,
    _table_exists,
)


_ROOT = Path(__file__).resolve().parents[4]
_MANIFEST = Path(__file__).with_name("qa_plan_execution_records.migration.json")
_TARGET_TABLES = (
    QA_PLAN_EXECUTION_TABLE,
    QA_PLAN_EXECUTION_RESULT_TABLE,
)


def test_governed_manifest_is_valid_digest_bound_and_exactly_scoped() -> None:
    payload = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    validate_manifest_payload(payload)
    source = payload["module_sources"][MIGRATION_NAME]
    digest = hashlib.sha256((_ROOT / source["path"]).read_bytes()).hexdigest()
    assert digest == source["sha256"]
    assert payload["profile"]["affected_surfaces"] == [
        {
            "table": QA_PLAN_EXECUTION_TABLE,
            "columns": list(QA_PLAN_EXECUTION_COLUMNS),
        },
        {
            "table": QA_PLAN_EXECUTION_RESULT_TABLE,
            "columns": list(QA_PLAN_EXECUTION_RESULT_COLUMNS),
        },
    ]


def test_source_checkout_wrapper_exposes_packaged_migration() -> None:
    assert source_wrapper.MIGRATION_NAME == MIGRATION_NAME
    assert source_wrapper.apply is apply
    assert source_wrapper.invariants is invariants


def _drop_target_schema(conn) -> None:
    conn.execute(f"DROP TABLE IF EXISTS {QA_PLAN_EXECUTION_RESULT_TABLE}")
    conn.execute(f"DROP TABLE IF EXISTS {QA_PLAN_EXECUTION_TABLE}")


def _schema_shape(conn) -> dict[str, dict[str, tuple]]:
    return {
        table: {
            "columns": tuple(_get_columns_with_types(conn, table)),
            "checks": tuple(_get_check_constraint_defs(conn, table)),
            "indexes": tuple(_get_indexes(conn, table)),
        }
        for table in _TARGET_TABLES
    }


def _execution_state(conn) -> dict[str, list[tuple]]:
    executions = conn.execute(
        "SELECT id,item_id,transition_id,actor_id,session_id,roster_digest,"
        "roster_json,cursor_ordinal,state,machine_lease_id,created_at,"
        "heartbeat_at,completed_at,release_reason "
        f"FROM {QA_PLAN_EXECUTION_TABLE} ORDER BY id"
    ).fetchall()
    results = conn.execute(
        "SELECT execution_id,ordinal,requirement_id,result_json,completed_at "
        f"FROM {QA_PLAN_EXECUTION_RESULT_TABLE} "
        "ORDER BY execution_id,ordinal"
    ).fetchall()
    return {
        "executions": [tuple(row) for row in executions],
        "results": [tuple(row) for row in results],
    }


def test_apply_matches_fixture_shape_and_reapplies_without_mutation(test_db) -> None:
    fixture_shape = _schema_shape(test_db)
    unrelated_tables = set(_get_tables(test_db)) - set(_TARGET_TABLES)
    method_state = [
        tuple(row)
        for row in test_db.execute(
            "SELECT id,updated_at FROM qa_methods ORDER BY id"
        ).fetchall()
    ]
    insert_item(test_db, id=90701, title="Execute durable QA plan")
    requirement = insert_qa_requirement(
        test_db,
        item_id=90701,
        qa_kind="plan_case",
    )
    requirement_id = int(requirement["id"])

    _drop_target_schema(test_db)
    test_db.commit()
    apply(test_db)
    invariants(test_db)

    assert _schema_shape(test_db) == fixture_shape
    assert set(_get_tables(test_db)) - set(_TARGET_TABLES) == unrelated_tables
    assert [
        tuple(row)
        for row in test_db.execute(
            "SELECT id,updated_at FROM qa_methods ORDER BY id"
        ).fetchall()
    ] == method_state

    test_db.execute(
        f"INSERT INTO {QA_PLAN_EXECUTION_TABLE}("
        "id,item_id,transition_id,actor_id,session_id,roster_digest,"
        "roster_json,cursor_ordinal,state,machine_lease_id,created_at,"
        "heartbeat_at"
        ") VALUES ('execution-1',90701,'implemented','operator-1',"
        "'session-1','digest-1','[]',1,'active',NULL,'then','then')"
    )
    test_db.execute(
        f"INSERT INTO {QA_PLAN_EXECUTION_RESULT_TABLE}("
        "execution_id,ordinal,requirement_id,result_json,completed_at"
        ") VALUES ('execution-1',1,%s,'{\"verdict\":\"pass\"}','then')",
        (requirement_id,),
    )
    test_db.commit()
    first_state = _execution_state(test_db)

    apply(test_db)
    invariants(test_db)
    apply(test_db)
    invariants(test_db)

    assert _execution_state(test_db) == first_state
    assert [
        tuple(row)
        for row in test_db.execute(
            "SELECT id,updated_at FROM qa_methods ORDER BY id"
        ).fetchall()
    ] == method_state


def test_apply_leaves_transaction_control_with_caller(test_db) -> None:
    _drop_target_schema(test_db)
    test_db.commit()

    apply(test_db)
    assert all(_table_exists(test_db, table) for table in _TARGET_TABLES)
    test_db.rollback()

    assert all(not _table_exists(test_db, table) for table in _TARGET_TABLES)


def test_core_schema_convergence_uses_permanent_execution_schema(test_db) -> None:
    from yoke_core.domain.schema_init import converge_core_schema

    _drop_target_schema(test_db)
    test_db.commit()

    converge_core_schema(test_db)

    invariants(test_db)


def test_schema_convergence_is_sqlite_portable_and_idempotent() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("CREATE TABLE qa_requirements (id INTEGER PRIMARY KEY)")
        apply(conn)
        invariants(conn)
        conn.execute("INSERT INTO qa_requirements(id) VALUES (1)")
        conn.execute(
            f"INSERT INTO {QA_PLAN_EXECUTION_TABLE}("
            "id,item_id,transition_id,session_id,roster_digest,roster_json,"
            "state,created_at,heartbeat_at"
            ") VALUES ('execution-1',1,'implemented','session-1','digest-1',"
            "'[]','active','then','then')"
        )
        conn.execute(
            f"INSERT INTO {QA_PLAN_EXECUTION_RESULT_TABLE}("
            "execution_id,ordinal,requirement_id,result_json,completed_at"
            ") VALUES ('execution-1',1,1,'{}','then')"
        )
        conn.commit()
        first_state = _execution_state(conn)

        apply(conn)
        invariants(conn)

        assert _execution_state(conn) == first_state
        assert {
            (table, index)
            for table, index in QA_PLAN_EXECUTION_INDEXES
            if index in _get_indexes(conn, table)
        } == set(QA_PLAN_EXECUTION_INDEXES)
    finally:
        conn.close()
