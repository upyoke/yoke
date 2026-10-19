"""Ordered migration coverage for dropping the retired item shepherd log."""

from __future__ import annotations

import importlib
import sqlite3

from yoke_core.domain.migration_serving_version import NEXT_RELEASE, declared_minimum


ENTRY_NAME = "0086_drop_item_shepherd_log"


def _entry():
    return importlib.import_module(f"yoke_core.domain.migrations.{ENTRY_NAME}")


def _columns(conn: sqlite3.Connection) -> set[str]:
    return {str(row[1]) for row in conn.execute("PRAGMA table_info(items)")}


def test_entry_requires_the_next_release_serving_floor() -> None:
    assert declared_minimum(_entry()) == NEXT_RELEASE


def test_apply_drops_the_column_and_keeps_every_item() -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE items (id INTEGER PRIMARY KEY, spec TEXT, shepherd_log TEXT)"
    )
    conn.execute("INSERT INTO items VALUES (1, 'Spec.', '## Shepherd Log')")

    _entry().apply(conn)
    _entry().apply(conn)
    _entry().invariants(conn)

    assert _columns(conn) == {"id", "spec"}
    assert conn.execute("SELECT id, spec FROM items").fetchall() == [(1, "Spec.")]


def test_apply_is_a_no_op_without_the_items_table() -> None:
    conn = sqlite3.connect(":memory:")

    _entry().apply(conn)
    _entry().invariants(conn)
