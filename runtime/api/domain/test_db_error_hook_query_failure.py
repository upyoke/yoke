"""Neutral DB-query failure detector tests."""

from __future__ import annotations

from yoke_core.domain.db_error_hook import detect_db_query_failure


def test_postgres_column_failure_names_stale_column() -> None:
    result = detect_db_query_failure(
        'yoke db read "SELECT owner_session_id FROM items"',
        'psycopg.errors.UndefinedColumn: column "owner_session_id" does not exist',
    )
    assert result is not None
    assert "unknown column `owner_session_id`" in result


def test_postgres_relation_failure_names_stale_table() -> None:
    result = detect_db_query_failure(
        'yoke db read "SELECT * FROM item_claims"',
        'ERROR:  relation "item_claims" does not exist',
    )
    assert result is not None
    assert "unknown table `item_claims`" in result
