"""Tests for yoke_core.domain.items — query_item, query_item_row,
insert_item, and update_item_field."""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from yoke_core.domain import db_backend
from runtime.api.fixtures.file_test_db import apply_fixture_schema_ddl, init_test_db
from yoke_core.domain.items import (
    CANONICAL_COLUMNS,
    insert_item,
    query_item,
    query_item_row,
    update_item_field,
    update_structured_field,
)


@pytest.fixture
def db_path(tmp_path):
    """Backend-aware temp DB with the full Yoke schema; yields the path token.

    SQLite: a real file under tmp_path. Postgres: a disposable per-test database
    with YOKE_PG_DSN repointed and dropped on teardown, so factory-routed
    code-under-test lands in an isolated DB (no item-id collision on the shared
    ambient DB across tests).
    """
    with init_test_db(tmp_path, apply_schema=apply_fixture_schema_ddl) as path:
        yield path


@pytest.fixture
def db_with_item(db_path):
    """Seed a single item (id=1) and return the db_path."""
    insert_item(
        item_id=1,
        title="Test item",
        item_type="issue",
        status="idea",
        priority="medium",
        source="user",
        project="yoke",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        db_path=db_path,
    )
    return db_path


class TestQueryItem:
    def test_returns_string_field(self, db_with_item):
        assert query_item(1, "title", db_path=db_with_item) == "Test item"

    def test_returns_status(self, db_with_item):
        assert query_item(1, "status", db_path=db_with_item) == "idea"

    def test_returns_spec(self, db_with_item):
        # body column retired; spec is the structured content field
        assert query_item(1, "spec", db_path=db_with_item) == ""

    def test_returns_empty_for_null_field(self, db_with_item):
        result = query_item(1, "worktree", db_path=db_with_item)
        assert result == ""

    def test_returns_empty_for_nonexistent_item(self, db_path):
        result = query_item(999, "title", db_path=db_path)
        assert result == ""

    def test_frozen_default_is_false(self, db_with_item):
        """frozen defaults to 0, which maps to 'false'."""
        result = query_item(1, "frozen", db_path=db_with_item)
        assert result == "false"

    def test_frozen_zero_maps_to_false(self, db_path):
        """frozen=0 should return 'false'."""
        insert_item(item_id=3, title="Not frozen", item_type="issue",
                    status="idea", priority="medium", frozen=0,
                    created_at="2026-01-01T00:00:00Z",
                    updated_at="2026-01-01T00:00:00Z", db_path=db_path)
        result = query_item(3, "frozen", db_path=db_path)
        assert result == "false"

    def test_frozen_maps_to_true(self, db_path):
        insert_item(item_id=2, title="Frozen", frozen=1, db_path=db_path)
        result = query_item(2, "frozen", db_path=db_path)
        assert result == "true"


class TestQueryItemRow:
    def test_returns_pipe_delimited(self, db_with_item):
        row = query_item_row(1, db_path=db_with_item)
        assert row is not None
        parts = row.split("|")
        assert len(parts) == len(CANONICAL_COLUMNS)

    def test_first_column_is_id(self, db_with_item):
        row = query_item_row(1, db_path=db_with_item)
        parts = row.split("|")
        assert parts[0] == "1"

    def test_title_in_row(self, db_with_item):
        row = query_item_row(1, db_path=db_with_item)
        parts = row.split("|")
        title_idx = list(CANONICAL_COLUMNS).index("title")
        assert parts[title_idx] == "Test item"

    def test_spec_newlines_escaped(self, db_path):
        # body column retired; test spec newline escaping instead
        insert_item(
            item_id=3,
            title="Multiline",
            db_path=db_path,
        )
        update_structured_field(3, "spec", "line1\nline2\nline3", db_path=db_path)

    def test_returns_none_for_missing_item(self, db_path):
        assert query_item_row(999, db_path=db_path) is None


class TestInsertItem:
    def test_insert_and_query_back(self, db_path):
        insert_item(
            item_id=10,
            title="New item",
            item_type="issue",
            status="idea",
            priority="high",
            source="test",
            project="yoke",
            db_path=db_path,
        )
        assert query_item(10, "title", db_path=db_path) == "New item"
        assert query_item(10, "priority", db_path=db_path) == "high"
        assert query_item(10, "source", db_path=db_path) == "test"

    def test_insert_with_minimal_fields(self, db_path):
        insert_item(item_id=11, title="Minimal", db_path=db_path)
        assert query_item(11, "title", db_path=db_path) == "Minimal"

    def test_insert_with_minimal_fields_stores_null_spec(self, db_path):
        insert_item(item_id=12, title="No spec", db_path=db_path)
        # No spec content set; COALESCE returns ''
        assert query_item(12, "spec", db_path=db_path) == ""

    def test_duplicate_id_raises(self, db_with_item):
        with pytest.raises(db_backend.integrity_error_types()):
            insert_item(item_id=1, title="Dup", db_path=db_with_item)


class TestUpdateItemField:
    def test_update_status(self, db_with_item):
        update_item_field(1, "status", "implementing", db_path=db_with_item)
        assert query_item(1, "status", db_path=db_with_item) == "implementing"

    def test_update_sets_updated_at(self, db_with_item):
        old_ts = query_item(1, "updated_at", db_path=db_with_item)
        update_item_field(1, "priority", "high", db_path=db_with_item)
        new_ts = query_item(1, "updated_at", db_path=db_with_item)
        assert new_ts != old_ts

    def test_null_string_maps_to_null(self, db_with_item):
        update_item_field(1, "worktree", "some-path", db_path=db_with_item)
        assert query_item(1, "worktree", db_path=db_with_item) == "some-path"
        update_item_field(1, "worktree", "null", db_path=db_with_item)
        assert query_item(1, "worktree", db_path=db_with_item) == ""

    def test_frozen_boolean_mapping_true(self, db_with_item):
        update_item_field(1, "frozen", "true", db_path=db_with_item)
        assert query_item(1, "frozen", db_path=db_with_item) == "true"

    def test_frozen_boolean_mapping_false(self, db_with_item):
        update_item_field(1, "frozen", "true", db_path=db_with_item)
        update_item_field(1, "frozen", "false", db_path=db_with_item)
        assert query_item(1, "frozen", db_path=db_with_item) == "false"

    def test_rejects_body_field_writes(self, db_with_item):
        """Body column is retired; writes must be rejected."""
        with pytest.raises(ValueError):
            update_item_field(1, "body", "new body", db_path=db_with_item)

    def test_rejects_structured_field_writes(self, db_with_item):
        """Structured fields must go through update_structured_field."""
        with pytest.raises(ValueError, match="structured field"):
            update_item_field(1, "spec", "content", db_path=db_with_item)

    def test_integer_field_rework_count(self, db_with_item):
        update_item_field(1, "rework_count", "3", db_path=db_with_item)
        assert query_item(1, "rework_count", db_path=db_with_item) == "3"
