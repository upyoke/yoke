"""Ordered migration coverage for the execution lanes -> levels rename."""

from __future__ import annotations

import importlib
import json
import sqlite3

import pytest

from yoke_core.domain.migration_serving_version import NEXT_RELEASE, declared_minimum


MIGRATION = importlib.import_module(
    "yoke_core.domain.migrations.0059_rename_session_lanes_to_levels"
)


def _columns(conn: sqlite3.Connection) -> set[str]:
    return {str(row[1]) for row in conn.execute("PRAGMA table_info(harness_sessions)")}


def _indexes(conn: sqlite3.Connection) -> set[str]:
    return {str(row[1]) for row in conn.execute("PRAGMA index_list(harness_sessions)")}


def _routing_database(settings: dict) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE project_capabilities "
        "(id INTEGER PRIMARY KEY, type TEXT, settings TEXT)"
    )
    conn.execute(
        "INSERT INTO project_capabilities VALUES (1, 'session-routing', ?)",
        (json.dumps(settings),),
    )
    return conn


def _stored(conn: sqlite3.Connection) -> dict:
    return json.loads(
        conn.execute("SELECT settings FROM project_capabilities").fetchone()[0]
    )


def test_entry_requires_the_next_release_serving_floor() -> None:
    assert declared_minimum(MIGRATION) == NEXT_RELEASE


def test_column_and_index_rename_preserves_every_stamped_level() -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE harness_sessions (session_id TEXT PRIMARY KEY, "
        "execution_lane TEXT NOT NULL DEFAULT 'primary')"
    )
    conn.execute(
        "CREATE INDEX idx_harness_sessions_lane ON harness_sessions(execution_lane)"
    )
    conn.execute("INSERT INTO harness_sessions VALUES ('session-1', 'DARIUS')")

    MIGRATION.apply(conn)
    MIGRATION.apply(conn)
    MIGRATION.invariants(conn)

    assert _columns(conn) == {"session_id", "execution_level"}
    assert _indexes(conn) >= {"idx_harness_sessions_level"}
    assert "idx_harness_sessions_lane" not in _indexes(conn)
    assert conn.execute("SELECT execution_level FROM harness_sessions").fetchone() == (
        "DARIUS",
    )


def test_column_converges_when_both_spellings_already_exist() -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE harness_sessions (session_id TEXT PRIMARY KEY, "
        "execution_lane TEXT, execution_level TEXT)"
    )
    conn.executemany(
        "INSERT INTO harness_sessions VALUES (?, ?, ?)",
        (("old", "ALTMAN", None), ("new", None, "MUSKY")),
    )

    MIGRATION.apply(conn)
    MIGRATION.invariants(conn)

    assert _columns(conn) == {"session_id", "execution_level"}
    assert conn.execute(
        "SELECT session_id, execution_level FROM harness_sessions ORDER BY session_id"
    ).fetchall() == [("new", "MUSKY"), ("old", "ALTMAN")]


def test_routing_documents_converge_to_level_keys_and_validate() -> None:
    conn = _routing_database(
        {
            "executor_default_lanes": {"claude*": "DARIUS", "codex*": "ALTMAN"},
            "executor_default_lane_cursor": "DARIUS",
            "lane_metadata": {
                "DARIUS": {"label": "DARIUS", "glyph": "\U0001f40e"},
                "ALTMAN": {"label": "ALTMAN", "glyph": "\U0001f453"},
            },
            "lane_rules": [{"model": "gpt-*", "lane": "ALTMAN"}],
            "max_chain_steps": 3,
        }
    )

    MIGRATION.apply(conn)
    MIGRATION.invariants(conn)
    result = _stored(conn)

    assert result == {
        "executor_default_levels": {"claude*": "DARIUS", "codex*": "ALTMAN"},
        "executor_default_level_cursor": "DARIUS",
        "level_metadata": {
            "DARIUS": {"label": "DARIUS", "glyph": "\U0001f40e"},
            "ALTMAN": {"label": "ALTMAN", "glyph": "\U0001f453"},
        },
        "level_rules": [{"model": "gpt-*", "level": "ALTMAN"}],
        "max_chain_steps": 3,
    }
    before = conn.total_changes
    MIGRATION.apply(conn)
    assert conn.total_changes == before


def test_document_carrying_both_spellings_refuses_with_recovery() -> None:
    conn = _routing_database(
        {"lane_metadata": {"A": {"label": "A"}}, "level_metadata": {}}
    )
    with pytest.raises(RuntimeError, match="session_routing_level_keys_conflict"):
        MIGRATION.apply(conn)


def test_invariants_detect_a_residual_lane_key() -> None:
    conn = _routing_database({"lane_rules": []})
    with pytest.raises(AssertionError, match="lane_rules"):
        MIGRATION.invariants(conn)


def test_missing_tables_are_safe() -> None:
    conn = sqlite3.connect(":memory:")
    MIGRATION.apply(conn)
    MIGRATION.invariants(conn)
