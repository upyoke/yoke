"""The permanent history entry that removes the stored steering-document pair."""

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
from yoke_core.domain.schema_common import _column_exists, _index_exists


ENTRY_NAME = "0028_remove_strategy_doc_claim_pair"


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
        f"id INTEGER PRIMARY KEY, {entry.RETIRED_COLUMN} INTEGER, "
        "strategy_doc_slug TEXT NOT NULL)"
    )
    conn.execute(
        f"CREATE UNIQUE INDEX {entry.RETIRED_INDEX} "
        f"ON {entry.TABLE}({entry.RETIRED_COLUMN}) "
        f"WHERE {entry.RETIRED_COLUMN} IS NOT NULL"
    )
    conn.execute(
        f"INSERT INTO {entry.TABLE} (id, {entry.RETIRED_COLUMN}, "
        "strategy_doc_slug) VALUES (1, 9, 'AREA-PLAN')"
    )
    return conn


def test_entry_drops_the_retired_index_and_column() -> None:
    conn = _legacy_table()

    entry.apply(conn)
    entry.invariants(conn)

    assert not _column_exists(conn, entry.TABLE, entry.RETIRED_COLUMN)
    assert not _index_exists(conn, entry.RETIRED_INDEX, entry.TABLE)
    assert conn.execute(
        f"SELECT id, strategy_doc_slug FROM {entry.TABLE}"
    ).fetchone() == (1, "AREA-PLAN")


def test_entry_is_idempotent_when_the_pair_is_already_absent() -> None:
    conn = _legacy_table()

    entry.apply(conn)
    entry.apply(conn)

    entry.invariants(conn)


def test_entry_leaves_a_database_without_the_table_alone() -> None:
    conn = sqlite3.connect(":memory:")

    entry.apply(conn)
    entry.invariants(conn)


def test_entry_uses_the_next_release_serving_floor() -> None:
    directory = history_dir(migration_history_package)
    source = (directory / f"{ENTRY_NAME}.py").read_text(encoding="utf-8")

    assert removes_a_surface(source)
    assert entry.MINIMUM_SERVING_VERSION == NEXT_RELEASE
    assert declared_minimum(entry) == NEXT_RELEASE
