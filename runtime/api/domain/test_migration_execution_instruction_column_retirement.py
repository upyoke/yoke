"""The entry that reduces an execution instruction to its prose.

Three columns described the instruction without being it, and each could
disagree with it. Dropping them is destructive on a live table, so the entry
carries a serving floor and proves both halves: the retired columns are gone,
and the prose the instruction actually is survives.
"""

from __future__ import annotations

import sqlite3

import pytest

from yoke_core.domain import migrations as migration_history_package
from yoke_core.domain.migration_history import (
    history_dir,
    load_migration_module,
    ordered_entries,
)
from yoke_core.domain.migration_serving_version import (
    declared_minimum,
    removes_a_surface,
)
from yoke_core.domain.schema_common import _column_exists

ENTRY_NAME = "0007_retire_execution_instruction_title_ordering_status"


def _entry():
    """Load the entry the way the applier does: by path, not by import name.

    An entry's filename begins with digits, so it is not importable as a module
    attribute — which is also why its identity is the filename.
    """
    directory = history_dir(migration_history_package)
    match = next(
        record for record in ordered_entries(directory)
        if record.name == ENTRY_NAME
    )
    return load_migration_module(directory / f"{match.name}.py", match.name)


entry = _entry()


def _table_with_retired_columns() -> sqlite3.Connection:
    """A database still shaped the way it was before the retirement."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        f"""
        CREATE TABLE {entry.INSTRUCTIONS_TABLE} (
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            applies_to_all_workflows INTEGER NOT NULL DEFAULT 0,
            applies_to_all_projects INTEGER NOT NULL DEFAULT 0,
            ordering INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'active',
            updated_by_actor_id INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )
    conn.execute(
        f"INSERT INTO {entry.INSTRUCTIONS_TABLE} "
        "(id, title, content, ordering, status, created_at, updated_at) "
        "VALUES (1, 'A title', 'The prose an agent obeys', 3, 'active', "
        "'2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')"
    )
    conn.commit()
    return conn


def test_the_retired_columns_are_dropped():
    conn = _table_with_retired_columns()

    entry.apply(conn)

    for column, _reason in entry.RETIRED_COLUMNS:
        assert not _column_exists(conn, entry.INSTRUCTIONS_TABLE, column)


def test_the_prose_survives_the_drop():
    """The point of the entry is to leave the instruction, not remove it."""
    conn = _table_with_retired_columns()

    entry.apply(conn)

    row = conn.execute(
        f"SELECT content FROM {entry.INSTRUCTIONS_TABLE} WHERE id = 1"
    ).fetchone()
    assert row[0] == "The prose an agent obeys"


def test_applying_twice_is_the_same_as_applying_once():
    """Idempotent against its own output already existing, not merely against
    having run: a column already absent is nothing to drop."""
    conn = _table_with_retired_columns()

    entry.apply(conn)
    entry.apply(conn)

    entry.invariants(conn)


def test_invariants_refuse_a_table_that_kept_a_retired_column():
    conn = _table_with_retired_columns()

    with pytest.raises(AssertionError, match="retired but still present"):
        entry.invariants(conn)


def test_invariants_refuse_a_table_that_lost_its_prose():
    """A drop that took content with it would have destroyed the
    instructions rather than trimmed them."""
    conn = _table_with_retired_columns()
    entry.apply(conn)
    conn.execute(f'ALTER TABLE "{entry.INSTRUCTIONS_TABLE}" DROP COLUMN "content"')

    with pytest.raises(AssertionError, match="required but absent"):
        entry.invariants(conn)


def test_a_database_without_the_table_is_left_alone():
    """A universe that never had instructions has nothing to retire."""
    conn = sqlite3.connect(":memory:")

    entry.apply(conn)
    entry.invariants(conn)


def test_the_entry_declares_a_serving_floor_because_it_removes_a_surface():
    """A rolled-back container reports itself current while reading columns
    that are gone, so the floor is what refuses it."""
    source = (
        history_dir(migration_history_package) / f"{ENTRY_NAME}.py"
    ).read_text(encoding="utf-8")
    assert removes_a_surface(source)
    assert declared_minimum(entry) == entry.MINIMUM_SERVING_VERSION
