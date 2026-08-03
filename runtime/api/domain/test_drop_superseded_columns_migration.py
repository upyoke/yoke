"""Coverage for the superseded-column history entry."""

from __future__ import annotations

import sqlite3

import pytest

from yoke_core.domain import migrations as migration_history_package
from yoke_core.domain.migration_history import (
    history_dir,
    load_migration_module,
    ordered_entries,
)

_ENTRY_SLUG = "drop_superseded_columns"
_entry = next(
    entry
    for entry in ordered_entries(history_dir(migration_history_package))
    if entry.name.endswith(_ENTRY_SLUG)
)
migration = load_migration_module(_entry.path, _entry.name)


def _connection_with_superseded_columns() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE items (id INTEGER PRIMARY KEY, title TEXT, "
        "worktree TEXT, flow TEXT, type TEXT, browser_qa_metadata TEXT)"
    )
    conn.execute(
        "CREATE TABLE events (id INTEGER PRIMARY KEY, event_name TEXT, "
        "parent_id TEXT, user_id TEXT)"
    )
    conn.execute(
        "CREATE TABLE epic_tasks (id INTEGER PRIMARY KEY, title TEXT, "
        "blocked_by TEXT, branch TEXT, worktree TEXT, worktree_path TEXT)"
    )
    conn.execute(
        "CREATE TABLE path_claims (id INTEGER PRIMARY KEY, state TEXT, "
        "session_id TEXT, item_id INTEGER, work_claim_id INTEGER, "
        "actor_id INTEGER)"
    )
    conn.commit()
    return conn


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {
        row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }


def test_drops_every_superseded_column_and_keeps_the_rest() -> None:
    conn = _connection_with_superseded_columns()
    conn.execute("INSERT INTO items (id, title) VALUES (1, 'kept')")
    conn.commit()

    migration.apply(conn)
    migration.invariants(conn)

    assert _columns(conn, "items") == {"id", "title"}
    assert _columns(conn, "events") == {"id", "event_name"}
    assert _columns(conn, "epic_tasks") == {"id", "title"}
    assert _columns(conn, "path_claims") == {"id", "state"}
    # Dropping a column must not disturb the rows that carry the survivors.
    assert conn.execute("SELECT title FROM items WHERE id=1").fetchone()[0] == "kept"


def test_is_a_no_op_where_the_drops_already_landed() -> None:
    # Every authoritative install already applied these through the mechanism
    # that predated the ordered history, so re-running must be silent there.
    conn = _connection_with_superseded_columns()
    migration.apply(conn)

    migration.apply(conn)
    migration.invariants(conn)

    assert _columns(conn, "items") == {"id", "title"}


def test_skips_tables_that_do_not_exist() -> None:
    # A database carrying only some of these tables is legitimate; a missing
    # table is not a reason to fail a boot.
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, worktree TEXT)")
    conn.commit()

    migration.apply(conn)
    migration.invariants(conn)

    assert _columns(conn, "items") == {"id"}


def test_invariants_reject_a_surviving_column() -> None:
    conn = _connection_with_superseded_columns()

    with pytest.raises(AssertionError, match="superseded but still present"):
        migration.invariants(conn)
