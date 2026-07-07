"""Fresh-schema index coverage tests for ``events_schema``.

Locks in the structural contract session-scoped telemetry lookups
depend on: ``cmd_init`` MUST create ``idx_events_session_event_tool``
so audit/correlation queries keyed on (session_id, event_name,
tool_use_id) never fall back to scanning every historical tool-call
row globally.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from yoke_core.domain.events_schema import (
    STOP_CLEANUP_INDEX_NAME,
    cmd_init,
    ensure_event_schema,
)
from yoke_core.domain.schema_common import _column_exists, _get_indexes
from runtime.api.fixtures.file_test_db import connect_test_db

STOP_CLEANUP_INDEX = STOP_CLEANUP_INDEX_NAME


def _open(db_path: Path) -> Any:
    conn = connect_test_db(str(db_path))
    return conn


def _index_names(conn: Any) -> set[str]:
    return set(_get_indexes(conn, "events"))


def _index_definition(conn: Any, index_name: str) -> str:
    row = conn.execute(
        "SELECT indexdef FROM pg_indexes "
        "WHERE schemaname=current_schema() AND indexname=%s",
        (index_name,),
    ).fetchone()
    assert row is not None
    return str(row[0])


@pytest.fixture
def fresh_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "fresh.db"
    cmd_init(str(db_path))
    return db_path


def test_cmd_init_creates_stop_cleanup_index(fresh_db: Path) -> None:
    """Fresh DB initialization must register the session-scoped composite."""
    conn = _open(fresh_db)
    try:
        assert STOP_CLEANUP_INDEX in _index_names(conn)
    finally:
        conn.close()


def test_stop_cleanup_index_is_partial_and_session_first(fresh_db: Path) -> None:
    """The index must be the (session_id, event_name, tool_use_id) shape.

    A different column order would push session-scoped telemetry
    lookups back onto the global event_name index.
    """
    conn = _open(fresh_db)
    try:
        ddl = _index_definition(conn, STOP_CLEANUP_INDEX).lower()
        assert "session_id" in ddl
        assert "event_name" in ddl
        assert "tool_use_id" in ddl
        # Partial index keeps the population narrow to the relevant rows.
        assert "where" in ddl
        assert "tool_use_id is not null" in ddl
        # session_id must appear before event_name and tool_use_id so the
        # outer Started-row scan can seek by session first.
        sid_pos = ddl.index("session_id")
        evn_pos = ddl.index("event_name")
        tu_pos = ddl.index("tool_use_id")
        assert sid_pos < evn_pos < tu_pos
    finally:
        conn.close()


def test_cmd_init_is_idempotent_for_stop_cleanup_index(fresh_db: Path) -> None:
    """Re-running ``cmd_init`` must not duplicate or drop the index."""
    before = _index_names(_open(fresh_db))
    cmd_init(str(fresh_db))
    after = _index_names(_open(fresh_db))
    assert STOP_CLEANUP_INDEX in before
    assert STOP_CLEANUP_INDEX in after
    assert before == after


def test_cmd_init_creates_no_board_activity_indexes(fresh_db: Path) -> None:
    """Board activity reads item_activity_days post telemetry-only-events — fresh DBs must
    not grow the retired events-scan indexes."""
    conn = _open(fresh_db)
    try:
        names = _index_names(conn)
        assert not any("board_activity" in name for name in names)
    finally:
        conn.close()


def test_existing_events_table_does_not_gain_actor_id_outside_migration(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "legacy.db"
    conn = _open(db_path)
    try:
        conn.execute("DROP TABLE IF EXISTS events CASCADE")
        conn.execute(
            """
            CREATE TABLE events (
                id INTEGER PRIMARY KEY,
                event_id TEXT UNIQUE NOT NULL,
                source_type TEXT NOT NULL,
                session_id TEXT NOT NULL,
                severity TEXT NOT NULL DEFAULT 'INFO',
                event_kind TEXT NOT NULL,
                event_type TEXT NOT NULL,
                event_name TEXT NOT NULL,
                user_id TEXT,
                org_id TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()

        ensure_event_schema(conn)

        assert not _column_exists(conn, "events", "actor_id")
        assert "idx_events_actor_id" not in _index_names(conn)
    finally:
        conn.close()
