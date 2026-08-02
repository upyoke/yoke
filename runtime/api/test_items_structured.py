"""Tests for structured item fields and multi-field updates."""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from runtime.api.fixtures.file_test_db import (
    apply_fixture_schema_ddl,
    connect_test_db,
    init_test_db,
)
from yoke_core.domain.items import (
    insert_item,
    query_item,
    update_item_multi,
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
    insert_item(
        item_id=1,
        title="Test item",
        workflow="issue",
        status="idea",
        priority="medium",
        source="user",
        project="yoke",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        db_path=db_path,
    )
    return db_path


class TestUpdateStructuredField:
    def test_writes_structured_content(self, db_with_item):
        update_structured_field(1, "spec", "# Spec\nContent here", db_path=db_with_item)
        assert query_item(1, "spec", db_path=db_with_item) == "# Spec\nContent here"

    def test_rejects_invalid_field(self, db_with_item):
        with pytest.raises(ValueError, match="Invalid structured field"):
            update_structured_field(1, "title", "bad", db_path=db_with_item)

    def test_empty_content_guard(self, db_with_item):
        """Refuses to overwrite non-empty content with empty."""
        update_structured_field(1, "spec", "existing content", db_path=db_with_item)
        with pytest.raises(ValueError, match="Refusing to overwrite"):
            update_structured_field(1, "spec", "", db_path=db_with_item)

    def test_empty_content_guard_whitespace(self, db_with_item):
        """Whitespace-only content counts as empty."""
        update_structured_field(1, "spec", "existing content", db_path=db_with_item)
        with pytest.raises(ValueError, match="Refusing to overwrite"):
            update_structured_field(1, "spec", "   \n  ", db_path=db_with_item)

    def test_empty_content_allowed_when_field_empty(self, db_with_item):
        """Writing empty to an already-empty field should not raise."""
        update_structured_field(1, "spec", "", db_path=db_with_item)
        # Should not raise -- field was empty

    def test_shrinkage_guard(self, db_with_item):
        """Refuses writes where new < 50% of old when old >= 10 lines."""
        big_content = "\n".join(f"line {i}" for i in range(20))
        update_structured_field(1, "spec", big_content, db_path=db_with_item)
        small_content = "just one line"
        with pytest.raises(ValueError, match="less than 50%"):
            update_structured_field(1, "spec", small_content, db_path=db_with_item)

    def test_shrinkage_guard_force_bypass(self, db_with_item):
        """Force flag bypasses the shrinkage guard."""
        big_content = "\n".join(f"line {i}" for i in range(20))
        update_structured_field(1, "spec", big_content, db_path=db_with_item)
        small_content = "just one line"
        update_structured_field(
            1, "spec", small_content, force=True, db_path=db_with_item
        )
        assert query_item(1, "spec", db_path=db_with_item) == small_content

    def test_shrinkage_guard_not_triggered_below_threshold(self, db_with_item):
        """Shrinkage guard only triggers when existing has >= 10 lines."""
        five_lines = "\n".join(f"line {i}" for i in range(5))
        update_structured_field(1, "spec", five_lines, db_path=db_with_item)
        one_line = "short"
        # Should succeed -- existing is under 10 lines
        update_structured_field(1, "spec", one_line, db_path=db_with_item)
        assert query_item(1, "spec", db_path=db_with_item) == one_line

    def test_content_field_tracks_spec_updated_at(self, db_with_item):
        """Content fields (spec, design_spec, etc.) should set spec_updated_at."""
        update_structured_field(
            1, "spec", "new spec", source="architect", db_path=db_with_item
        )
        conn = connect_test_db(db_with_item)
        row = conn.execute(
            "SELECT spec_updated_at, spec_updated_by FROM items WHERE id = 1"
        ).fetchone()
        conn.close()
        assert row[0] is not None  # spec_updated_at set
        assert row[1] == "architect"  # spec_updated_by set

    def test_non_content_field_no_spec_tracking(self, db_with_item):
        """Non-content fields (shepherd_log etc.) should not touch spec_updated_*."""
        update_structured_field(1, "shepherd_log", "log entry", db_path=db_with_item)
        conn = connect_test_db(db_with_item)
        row = conn.execute("SELECT spec_updated_at FROM items WHERE id = 1").fetchone()
        conn.close()
        assert row[0] is None


class TestUpdateItemMulti:
    def test_batch_update(self, db_with_item):
        update_item_multi(
            1,
            {"priority": "high", "title": "Updated item"},
            db_path=db_with_item,
        )
        assert query_item(1, "priority", db_path=db_with_item) == "high"
        assert query_item(1, "title", db_path=db_with_item) == "Updated item"

    def test_sets_updated_at(self, db_with_item):
        old_ts = query_item(1, "updated_at", db_path=db_with_item)
        update_item_multi(1, {"priority": "low"}, db_path=db_with_item)
        new_ts = query_item(1, "updated_at", db_path=db_with_item)
        assert new_ts != old_ts

    def test_rejects_body_in_batch(self, db_with_item):
        with pytest.raises(ValueError, match="Raw body writes are no longer supported"):
            update_item_multi(1, {"body": "nope"}, db_path=db_with_item)

    @pytest.mark.parametrize(
        "field",
        [
            "status",
            "workflow_id",
            "workflow_posture",
            "workflow_version_id",
        ],
    )
    def test_rejects_workflow_controlled_fields(
        self,
        db_with_item,
        field,
    ):
        with pytest.raises(ValueError, match="canonical workflow surface"):
            update_item_multi(1, {field: "x"}, db_path=db_with_item)

    def test_rejects_empty_pairs(self, db_with_item):
        with pytest.raises(ValueError, match="No field"):
            update_item_multi(1, {}, db_path=db_with_item)

    def test_frozen_mapping_in_batch(self, db_with_item):
        update_item_multi(1, {"frozen": "true"}, db_path=db_with_item)
        assert query_item(1, "frozen", db_path=db_with_item) == "true"

    def test_null_mapping_in_batch(self, db_with_item):
        update_item_multi(1, {"blocked_reason": "paused"}, db_path=db_with_item)
        assert query_item(1, "blocked_reason", db_path=db_with_item) == "paused"
        update_item_multi(1, {"blocked_reason": "null"}, db_path=db_with_item)
        assert query_item(1, "blocked_reason", db_path=db_with_item) == ""
