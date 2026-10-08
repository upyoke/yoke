"""The permanent history entry that drops relays' advertised launch defaults."""

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
    NEXT_RELEASE,
    declared_minimum,
    removes_a_surface,
)
from yoke_core.domain.schema_common import _column_exists


ENTRY_NAME = "0064_drop_relay_launch_defaults"


def _entry():
    directory = history_dir(migration_history_package)
    record = next(
        entry for entry in ordered_entries(directory) if entry.name == ENTRY_NAME
    )
    return load_migration_module(directory / f"{record.name}.py", record.name)


entry = _entry()


def _legacy_relays() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE session_relays ("
        "relay_id TEXT PRIMARY KEY, machine_id TEXT NOT NULL, "
        "preferred_session_models TEXT DEFAULT NULL, "
        "preferred_session_reasoning_efforts TEXT DEFAULT NULL)"
    )
    conn.execute(
        "INSERT INTO session_relays VALUES "
        "('relay-1', 'machine-1', '{\"codex-cli\": \"gpt-5\"}', '{}')"
    )
    return conn


def test_entry_names_both_relay_launch_default_columns() -> None:
    assert entry.TABLE == "session_relays"
    assert set(entry.RETIRED_COLUMNS) == {
        "preferred_session_models",
        "preferred_session_reasoning_efforts",
    }


def test_entry_drops_both_columns_and_keeps_the_relay_rows() -> None:
    conn = _legacy_relays()

    entry.apply(conn)
    entry.invariants(conn)

    for column in entry.RETIRED_COLUMNS:
        assert not _column_exists(conn, entry.TABLE, column)
    assert conn.execute(
        "SELECT relay_id, machine_id FROM session_relays"
    ).fetchall() == [("relay-1", "machine-1")]


def test_entry_drops_whichever_column_an_older_database_still_carries() -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE session_relays ("
        "relay_id TEXT PRIMARY KEY, preferred_session_reasoning_efforts TEXT)"
    )

    entry.apply(conn)

    entry.invariants(conn)


def test_entry_is_idempotent() -> None:
    conn = _legacy_relays()

    entry.apply(conn)
    entry.apply(conn)

    entry.invariants(conn)


def test_invariants_refuse_a_table_that_still_carries_a_column() -> None:
    conn = _legacy_relays()

    with pytest.raises(AssertionError, match="must be absent"):
        entry.invariants(conn)


def test_entry_leaves_a_database_without_relays_alone() -> None:
    conn = sqlite3.connect(":memory:")

    entry.apply(conn)
    entry.invariants(conn)


def test_entry_uses_the_next_release_serving_floor() -> None:
    directory = history_dir(migration_history_package)
    source = (directory / f"{ENTRY_NAME}.py").read_text(encoding="utf-8")

    assert removes_a_surface(source)
    assert entry.MINIMUM_SERVING_VERSION == NEXT_RELEASE
    assert declared_minimum(entry) == NEXT_RELEASE
