"""QA method capability-set cutover migration tests."""

from __future__ import annotations

import importlib
import json
import sqlite3


MIGRATION = importlib.import_module(
    "yoke_core.domain.migrations.0013_qa_method_capability_sets"
)


def _database() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE qa_methods (
            id TEXT PRIMARY KEY,
            required_capability_kind TEXT,
            required_capability_kinds TEXT NOT NULL DEFAULT '[]'
        );
        INSERT INTO qa_methods VALUES ('command', NULL, '[]');
        INSERT INTO qa_methods VALUES (
            'browser-check', 'browser-control', '["native-dialog-control"]'
        );
        INSERT INTO qa_methods VALUES (
            'machine-state-check', 'test-machine', '[]'
        );
        CREATE TABLE qa_requirements (
            id INTEGER PRIMARY KEY,
            method_id TEXT,
            capability_requirements TEXT,
            required_capability_kind TEXT
        );
        INSERT INTO qa_requirements VALUES (1, 'command', '[]', NULL);
        INSERT INTO qa_requirements VALUES (
            2, 'browser-check', '["browser-control"]', 'browser-control'
        );
        INSERT INTO qa_requirements VALUES (
            3, 'machine-state-check', NULL, 'test-machine'
        );
        INSERT INTO qa_requirements VALUES (
            4, NULL, 'browser-qa', NULL
        );
        INSERT INTO qa_requirements VALUES (
            5, NULL, '{"repo":true}', NULL
        );
        """
    )
    return conn


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}


def test_migration_backfills_sets_and_removes_singular_columns() -> None:
    conn = _database()
    MIGRATION.apply(conn)
    MIGRATION.invariants(conn)

    methods = {
        str(row["id"]): json.loads(str(row["required_capability_kinds"]))
        for row in conn.execute("SELECT id,required_capability_kinds FROM qa_methods")
    }
    requirements = {
        int(row["id"]): json.loads(str(row["capability_requirements"] or "[]"))
        for row in conn.execute(
            "SELECT id,capability_requirements FROM qa_requirements"
        )
    }
    assert methods == {
        "command": [],
        "browser-check": ["browser-control", "native-dialog-control"],
        "machine-state-check": ["test-machine"],
    }
    assert requirements == {
        1: [],
        2: ["browser-control"],
        3: ["test-machine"],
        4: ["browser-qa"],
        5: [],
    }
    assert "required_capability_kind" not in _columns(conn, "qa_methods")
    assert "required_capability_kind" not in _columns(conn, "qa_requirements")


def test_migration_replay_is_a_no_op() -> None:
    conn = _database()
    MIGRATION.apply(conn)
    before = list(
        conn.execute("SELECT id,required_capability_kinds FROM qa_methods ORDER BY id")
    )
    MIGRATION.apply(conn)
    MIGRATION.invariants(conn)
    after = list(
        conn.execute("SELECT id,required_capability_kinds FROM qa_methods ORDER BY id")
    )
    assert [tuple(row) for row in after] == [tuple(row) for row in before]


def test_migration_declares_the_next_serving_floor() -> None:
    assert MIGRATION.MINIMUM_SERVING_VERSION == "0.1.1+launch.243"
