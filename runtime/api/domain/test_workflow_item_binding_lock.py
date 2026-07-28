"""Portable schema coverage for item workflow binding locks."""

from __future__ import annotations

import sqlite3

import pytest

from yoke_core.domain.workflow_item_binding_lock import (
    lock_path_claim_workflow_binding,
    lock_work_claims_workflow_bindings,
    rollback_workflow_binding_write_errors,
)


def _connection(path_claim_columns: str) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY)")
    conn.execute(
        f"CREATE TABLE path_claims (id INTEGER PRIMARY KEY, {path_claim_columns})"
    )
    conn.executemany("INSERT INTO items (id) VALUES (?)", ((42,), (99,)))
    return conn


def test_legacy_path_claim_schema_locks_item_id() -> None:
    conn = _connection("item_id INTEGER")
    try:
        conn.execute("INSERT INTO path_claims (id, item_id) VALUES (1, 42)")
        assert lock_path_claim_workflow_binding(conn, 1) == (42,)
    finally:
        conn.close()


def test_typed_path_claim_schema_uses_only_item_owner() -> None:
    conn = _connection(
        "item_id INTEGER, owner_kind TEXT, owner_item_id INTEGER",
    )
    try:
        conn.execute(
            "INSERT INTO path_claims "
            "(id, item_id, owner_kind, owner_item_id) VALUES "
            "(1, 42, 'session', NULL), (2, NULL, 'item', 99)",
        )
        assert lock_path_claim_workflow_binding(conn, 1) == ()
        assert lock_path_claim_workflow_binding(conn, 2) == (99,)
    finally:
        conn.close()


def test_legacy_work_claim_schema_locks_item_id() -> None:
    conn = _connection("item_id INTEGER")
    try:
        conn.execute("CREATE TABLE work_claims (id INTEGER, item_id INTEGER)")
        conn.execute("INSERT INTO work_claims (id, item_id) VALUES (1, 42)")
        assert lock_work_claims_workflow_bindings(conn, (1,)) == (42,)
    finally:
        conn.close()


def test_typed_work_claim_schema_locks_item_and_epic_parents() -> None:
    conn = _connection("item_id INTEGER")
    try:
        conn.execute(
            "CREATE TABLE work_claims ("
            "id INTEGER, target_kind TEXT, item_id INTEGER, epic_id INTEGER)"
        )
        conn.execute(
            "INSERT INTO work_claims "
            "(id, target_kind, item_id, epic_id) VALUES "
            "(1, 'item', 42, NULL), "
            "(2, 'epic_task', NULL, 99), "
            "(3, 'process', NULL, NULL)"
        )
        assert lock_work_claims_workflow_bindings(conn, (3, 2, 1)) == (42, 99)
    finally:
        conn.close()


def test_caller_owned_failure_does_not_rollback_outer_transaction() -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE effects (name TEXT)")

    @rollback_workflow_binding_write_errors
    def fail_after_write(conn, *, commit=True):
        conn.execute("INSERT INTO effects VALUES ('inner')")
        raise RuntimeError("failed")

    try:
        conn.execute("INSERT INTO effects VALUES ('outer')")
        with pytest.raises(RuntimeError, match="failed"):
            fail_after_write(conn, commit=False)
        assert conn.execute("SELECT name FROM effects ORDER BY rowid").fetchall() == [
            ("outer",),
            ("inner",),
        ]
        conn.rollback()
    finally:
        conn.close()


def test_self_committing_failure_rolls_back_transaction() -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE effects (name TEXT)")

    @rollback_workflow_binding_write_errors
    def fail_after_write(conn, *, commit=True):
        conn.execute("INSERT INTO effects VALUES ('inner')")
        raise RuntimeError("failed")

    try:
        conn.execute("INSERT INTO effects VALUES ('outer')")
        with pytest.raises(RuntimeError, match="failed"):
            fail_after_write(conn)
        assert conn.execute("SELECT name FROM effects").fetchall() == []
    finally:
        conn.close()
