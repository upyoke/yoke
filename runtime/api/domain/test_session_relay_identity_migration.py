"""Ordered migration coverage for required relay identity columns."""

from __future__ import annotations

import sqlite3

import pytest

from yoke_core.domain import migrations as migration_history_package
from yoke_core.domain.migration_history import (
    history_dir,
    load_migration_module,
    ordered_entries,
)
from yoke_core.domain.migration_serving_version import NEXT_RELEASE, declared_minimum
from yoke_core.domain.schema_common import _column_exists


ENTRY_NAME = "0016_session_relay_identity"


def _entry():
    directory = history_dir(migration_history_package)
    record = next(
        candidate
        for candidate in ordered_entries(directory)
        if candidate.name == ENTRY_NAME
    )
    return load_migration_module(record.path, record.name)


entry = _entry()


def _retired_shape() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE actors (id INTEGER PRIMARY KEY);
        CREATE TABLE session_relays (
            relay_id TEXT PRIMARY KEY,
            machine_id TEXT NOT NULL
        );
        """
    )
    return conn


def test_apply_adds_required_identity_columns_and_is_idempotent() -> None:
    conn = _retired_shape()

    entry.apply(conn)
    entry.apply(conn)
    entry.invariants(conn)

    assert _column_exists(conn, "session_relays", "actor_id")
    assert _column_exists(conn, "session_relays", "hostname")


def test_invariants_reject_incomplete_existing_relay_identity() -> None:
    conn = _retired_shape()
    conn.execute(
        "INSERT INTO session_relays (relay_id, machine_id) VALUES (?, ?)",
        ("relay-1", "machine-1"),
    )

    with pytest.raises(AssertionError, match="relay identity must be complete"):
        entry.apply(conn)


def test_invariants_reject_a_missing_relay_table() -> None:
    conn = sqlite3.connect(":memory:")

    with pytest.raises(AssertionError, match=r"session_relays\.actor_id"):
        entry.invariants(conn)


def test_unreleased_entry_uses_the_next_release_floor() -> None:
    assert declared_minimum(entry) == NEXT_RELEASE
