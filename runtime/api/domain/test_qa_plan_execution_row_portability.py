"""Tuple-row portability for Stage-authoritative ordered QA rosters."""

from __future__ import annotations

import sqlite3

import psycopg

from runtime.api.domain.test_qa_plan_execution_authority import (
    _materialize_two_cases,
)
from runtime.api.fixtures.pg_testdb import (
    dsn_for_test_database,
    test_database,
)
from yoke_core.domain.qa_plan_execution import ordered_plan_requirements


def test_ordered_roster_accepts_default_psycopg_tuple_rows() -> None:
    with test_database() as setup:
        requirement_ids = _materialize_two_cases(setup, item_id=4420)
        with psycopg.connect(dsn_for_test_database(setup.info.dbname)) as conn:
            roster = ordered_plan_requirements(
                conn,
                item_id=4420,
                transition_id="implemented",
            )

    assert [row["requirement_id"] for row in roster] == requirement_ids
    assert [row["case_key"] for row in roster] == [
        "first-command",
        "second-command",
    ]


def test_ordered_roster_accepts_default_sqlite_tuple_rows() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute(
            "CREATE TABLE qa_requirements ("
            "id INTEGER PRIMARY KEY,item_id INTEGER,workflow_transition_id TEXT,"
            "plan_id INTEGER,plan_case_key TEXT,case_position INTEGER,"
            "baseline_position INTEGER,host_baseline TEXT,method_id TEXT,"
            "executor_id TEXT,waived_at TEXT)"
        )
        conn.execute(
            "INSERT INTO qa_requirements VALUES "
            "(1,7,'implemented',3,'first-command',1,1,NULL,'command',"
            "'worktree_run',NULL)"
        )

        roster = ordered_plan_requirements(
            conn,
            item_id=7,
            transition_id="implemented",
        )
    finally:
        conn.close()

    assert roster == [
        {
            "requirement_id": 1,
            "plan_id": 3,
            "case_key": "first-command",
            "case_position": 1,
            "baseline_position": 1,
            "host_baseline": None,
            "method_id": "command",
            "executor_id": "worktree_run",
        }
    ]
