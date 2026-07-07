"""Tests for yoke_core.board.db — BoardDB connection wrapper.

Covers:
- query / scalar / query_quiet methods
- Context manager lifecycle
- Missing-table graceful degradation
"""

from __future__ import annotations

import psycopg
import pytest

from yoke_core.board.db import BoardDB


class TestBoardDBQuery:
    """Query helper methods."""

    def test_query_returns_list_of_tuples(self, test_db):
        rows = test_db.query("SELECT id, emoji FROM projects")
        assert isinstance(rows, list)
        assert len(rows) >= 1
        assert isinstance(rows[0], tuple)

    def test_query_empty_result(self, test_db):
        rows = test_db.query("SELECT id FROM items WHERE id = -1")
        assert rows == []

    def test_scalar_returns_value(self, test_db):
        val = test_db.scalar("SELECT COUNT(*) FROM projects")
        assert val >= 1

    def test_scalar_returns_none_for_empty(self, test_db):
        val = test_db.scalar("SELECT id FROM items WHERE id = -1")
        assert val is None

    def test_query_with_params(self, test_db):
        rows = test_db.query("SELECT id FROM projects WHERE slug = %s", ("yoke",))
        assert len(rows) == 1
        assert rows[0][0] == 1


class TestBoardDBQueryQuiet:
    """query_quiet graceful degradation for missing tables."""

    def test_missing_table_returns_empty(self, test_db):
        rows = test_db.query_quiet("SELECT * FROM nonexistent_table")
        assert rows == []

    def test_missing_column_returns_empty(self, test_db):
        rows = test_db.query_quiet("SELECT nonexistent_col FROM projects")
        assert rows == []

    def test_normal_query_works(self, test_db):
        rows = test_db.query_quiet("SELECT id FROM projects")
        assert len(rows) >= 1

    def test_real_error_propagates(self, test_db):
        """Errors other than missing table/column should raise."""
        with pytest.raises(psycopg.Error):
            test_db.query_quiet("THIS IS NOT SQL")


class TestBoardDBLifecycle:
    """Context manager and close behavior."""

    def test_context_manager(self, test_db_path):
        with BoardDB(test_db_path) as db:
            assert db.scalar("SELECT 1") == 1
        # After exit, connection is closed
        with pytest.raises(Exception):
            db.query("SELECT 1")

    def test_explicit_close(self, test_db_path):
        db = BoardDB(test_db_path)
        db.close()
        with pytest.raises(Exception):
            db.query("SELECT 1")
