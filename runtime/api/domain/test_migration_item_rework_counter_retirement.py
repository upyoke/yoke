"""The permanent history entry that removes the unused item counter."""

from __future__ import annotations

import sqlite3

from yoke_core.domain import migrations as migration_history_package
from yoke_core.domain.migration_history import (
    history_dir,
    load_migration_module,
    ordered_entries,
)
from yoke_core.domain.migration_serving_version import (
    NEXT_RELEASE,
    declared_minimum,
    removes_a_surface,
)
from yoke_core.domain.schema_common import _column_exists


ENTRY_NAME = "0026_remove_item_rework_counter"


def _entry():
    directory = history_dir(migration_history_package)
    record = next(
        entry for entry in ordered_entries(directory) if entry.name == ENTRY_NAME
    )
    return load_migration_module(directory / f"{record.name}.py", record.name)


entry = _entry()


def _legacy_table() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        f"CREATE TABLE {entry.TABLE} ("
        f"id INTEGER PRIMARY KEY, {entry.RETIRED_COLUMN} INTEGER DEFAULT 0, "
        "title TEXT NOT NULL)"
    )
    conn.execute(
        f"INSERT INTO {entry.TABLE} (id, {entry.RETIRED_COLUMN}, title) "
        "VALUES (1, 0, 'kept')"
    )
    return conn


def test_entry_drops_only_the_retired_column() -> None:
    conn = _legacy_table()

    entry.apply(conn)
    entry.invariants(conn)

    assert not _column_exists(conn, entry.TABLE, entry.RETIRED_COLUMN)
    assert conn.execute(f"SELECT id,title FROM {entry.TABLE}").fetchone() == (1, "kept")


def test_entry_is_idempotent_when_the_column_is_already_absent() -> None:
    conn = _legacy_table()

    entry.apply(conn)
    entry.apply(conn)

    entry.invariants(conn)


def test_entry_leaves_a_database_without_items_alone() -> None:
    conn = sqlite3.connect(":memory:")

    entry.apply(conn)
    entry.invariants(conn)


def test_entry_uses_the_next_release_serving_floor() -> None:
    directory = history_dir(migration_history_package)
    source = (directory / f"{ENTRY_NAME}.py").read_text(encoding="utf-8")

    assert removes_a_surface(source)
    assert entry.MINIMUM_SERVING_VERSION == NEXT_RELEASE
    assert declared_minimum(entry) == NEXT_RELEASE
