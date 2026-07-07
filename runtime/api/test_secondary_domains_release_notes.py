"""Tests for yoke_core.domain.release_notes."""
from __future__ import annotations

import pytest

from runtime.api.conftest import insert_item


TEST_ITEM_ID = 42
TEST_ITEM_REF = f"YOK-{TEST_ITEM_ID}"


class TestReleaseNotes:
    def test_insert_and_list(self, test_db):
        from yoke_core.domain.release_notes import cmd_insert, cmd_list
        insert_item(test_db, id=TEST_ITEM_ID, title="Test", project="yoke")
        result = cmd_insert(
            test_db, TEST_ITEM_ID, "features", "New feature", "2024-01-01", "yoke"
        )
        assert TEST_ITEM_REF in result
        assert "features" in result

        listed = cmd_list(test_db, version="2024-01-01")
        assert str(TEST_ITEM_ID) in listed
        assert "features" in listed

    def test_insert_invalid_category(self, test_db):
        insert_item(test_db, id=1, title="Test")
        with pytest.raises(ValueError, match="invalid category"):
            from yoke_core.domain.release_notes import cmd_insert
            cmd_insert(test_db, 1, "bogus", "Title")

    def test_exists(self, test_db):
        from yoke_core.domain.release_notes import cmd_insert, cmd_exists
        insert_item(test_db, id=10, title="Test", project="yoke")
        cmd_insert(test_db, 10, "bug_fixes", "Fix", "2024-03-01", "yoke")
        assert cmd_exists(test_db, 10, "2024-03-01") is True
        assert cmd_exists(test_db, 10, "9999-01-01") is False

    def test_list_by_project(self, test_db):
        from yoke_core.domain.release_notes import cmd_insert, cmd_list
        insert_item(test_db, id=1, title="A", project="yoke")
        insert_item(test_db, id=2, title="B", project="buzz")
        cmd_insert(test_db, 1, "features", "F1", "v1", "yoke")
        cmd_insert(test_db, 2, "features", "F2", "v1", "buzz")
        result = cmd_list(test_db, project="buzz")
        assert "F2" in result
        assert "F1" not in result
