"""Ordered migration coverage for durable native-turn posture."""

from __future__ import annotations

import sqlite3

import pytest

from yoke_core.domain import migrations as migration_history_package
from yoke_core.domain.migration_history import (
    history_dir,
    load_migration_module,
    ordered_entries,
)
from yoke_core.domain.migration_serving_version import declared_minimum


ENTRY_NAME = "0017_session_turn_posture"


def _entry():
    directory = history_dir(migration_history_package)
    record = next(
        candidate
        for candidate in ordered_entries(directory)
        if candidate.name == ENTRY_NAME
    )
    return load_migration_module(record.path, record.name)


entry = _entry()


def test_apply_adds_constrained_posture_columns_and_is_idempotent() -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE harness_sessions (session_id TEXT PRIMARY KEY)")
    conn.execute("INSERT INTO harness_sessions VALUES ('s1')")

    entry.apply(conn)
    entry.apply(conn)
    entry.invariants(conn)

    assert conn.execute(
        "SELECT turn_posture,turn_posture_at FROM harness_sessions"
    ).fetchone() == ("unknown", None)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "UPDATE harness_sessions SET turn_posture='idle' WHERE session_id='s1'"
        )


def test_invariants_reject_missing_harness_session_table() -> None:
    with pytest.raises(AssertionError, match="turn posture columns missing"):
        entry.invariants(sqlite3.connect(":memory:"))


@pytest.mark.parametrize(
    ("posture_ddl", "message"),
    (
        (
            "TEXT DEFAULT 'unknown' "
            "CHECK(turn_posture IN ('running','waiting','unknown'))",
            "NOT NULL",
        ),
        (
            "TEXT NOT NULL CHECK(turn_posture IN ('running','waiting','unknown'))",
            "default to unknown",
        ),
        ("TEXT NOT NULL DEFAULT 'unknown'", "constrain the supported domain"),
    ),
)
def test_invariants_reject_relaxed_posture_contract(
    posture_ddl: str, message: str
) -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE harness_sessions (session_id TEXT PRIMARY KEY,"
        f"turn_posture {posture_ddl},turn_posture_at TEXT)"
    )

    with pytest.raises(AssertionError, match=message):
        entry.invariants(conn)


def test_additive_entry_does_not_raise_the_serving_floor() -> None:
    assert declared_minimum(entry) is None
