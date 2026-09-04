"""Ordered migration coverage for mode-independent session quiet reasons."""

from __future__ import annotations

import importlib
import sqlite3

from yoke_core.domain.migration_serving_version import NEXT_RELEASE, declared_minimum


ENTRY_NAME = "0039_session_quiet_reason"


def _entry():
    return importlib.import_module(f"yoke_core.domain.migrations.{ENTRY_NAME}")


def _columns(conn: sqlite3.Connection) -> set[str]:
    return {str(row[1]) for row in conn.execute("PRAGMA table_info(harness_sessions)")}


def test_entry_requires_the_next_release_serving_floor() -> None:
    assert declared_minimum(_entry()) == NEXT_RELEASE


def test_apply_renames_the_existing_reason_and_preserves_its_value() -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE harness_sessions (session_id TEXT PRIMARY KEY, "
        "parked_reason TEXT)"
    )
    conn.execute("INSERT INTO harness_sessions VALUES ('session-1', 'waiting on CI')")

    _entry().apply(conn)
    _entry().apply(conn)
    _entry().invariants(conn)

    assert _columns(conn) == {"session_id", "quiet_reason"}
    assert conn.execute(
        "SELECT quiet_reason FROM harness_sessions WHERE session_id='session-1'"
    ).fetchone() == ("waiting on CI",)


def test_apply_converges_when_additive_boot_already_created_the_new_column() -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE harness_sessions (session_id TEXT PRIMARY KEY, "
        "parked_reason TEXT, quiet_reason TEXT)"
    )
    conn.executemany(
        "INSERT INTO harness_sessions VALUES (?, ?, ?)",
        (
            ("old-value", "waiting on a blocking claim", None),
            ("new-value", None, "waiting on merge queue"),
        ),
    )

    _entry().apply(conn)
    _entry().invariants(conn)

    assert _columns(conn) == {"session_id", "quiet_reason"}
    assert conn.execute(
        "SELECT session_id, quiet_reason FROM harness_sessions ORDER BY session_id"
    ).fetchall() == [
        ("new-value", "waiting on merge queue"),
        ("old-value", "waiting on a blocking claim"),
    ]
