"""Neutral DB-query failure detector compatibility tests."""

from __future__ import annotations

from yoke_core.domain.db_error_hook import (
    detect_db_query_failure,
    detect_sqlite_failure,
)


def test_neutral_detector_name_preserves_sqlite_alias() -> None:
    command = "sqlite3 test.db 'SELECT 1'"
    output = "Exit code 1\nError: no such table"
    assert detect_db_query_failure(command, output) == detect_sqlite_failure(
        command, output
    )
