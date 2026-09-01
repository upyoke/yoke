"""Tests for yoke_core.domain.item_dependency graph commands."""
from __future__ import annotations

import pytest

from runtime.api.conftest import insert_item


class TestItemDependency:
    def test_dependency_add_and_list(self, test_db):
        from yoke_core.domain.item_dependency import cmd_dependency_add
        from yoke_core.domain.item_dependency_read import cmd_dependency_list
        insert_item(test_db, id=5, title="blocker")
        insert_item(test_db, id=10, title="dependent")
        cmd_dependency_add(test_db, "YOK-10", "YOK-5", "operator")
        result = cmd_dependency_list(test_db, "YOK-10")
        assert "depends-on" in result
        assert "YOK-5" in result

    def test_dependency_remove(self, test_db):
        from yoke_core.domain.item_dependency import (
            cmd_dependency_add,
            cmd_dependency_remove,
        )
        from yoke_core.domain.item_dependency_read import cmd_dependency_list
        insert_item(test_db, id=5, title="blocker")
        insert_item(test_db, id=10, title="dependent")
        cmd_dependency_add(test_db, "YOK-10", "YOK-5", "operator")
        cmd_dependency_remove(test_db, "YOK-10", "YOK-5")
        result = cmd_dependency_list(test_db, "YOK-10")
        assert result == ""

    def test_dependency_update(self, test_db):
        from yoke_core.domain.item_dependency import (
            cmd_dependency_add,
            cmd_dependency_update,
        )
        insert_item(test_db, id=15, title="blocker")
        insert_item(test_db, id=20, title="dependent")
        cmd_dependency_add(
            test_db, "YOK-20", "YOK-15", "shepherd",
            gate_point="activation",
        )
        cmd_dependency_update(
            test_db, "YOK-20", "YOK-15",
            rationale="Updated rationale",
        )

    def test_invalid_gate_point(self, test_db):
        from yoke_core.domain.item_dependency import cmd_dependency_add
        with pytest.raises(ValueError, match="gate_point"):
            cmd_dependency_add(
                test_db, "YOK-1", "YOK-2", "operator",
                gate_point="bogus",
            )

    def test_invalid_source(self, test_db):
        from yoke_core.domain.item_dependency import cmd_dependency_add
        with pytest.raises(ValueError, match="source"):
            cmd_dependency_add(test_db, "YOK-1", "YOK-2", "unknown_source")

    def test_dependency_enrich(self, test_db):
        from yoke_core.domain.item_dependency import cmd_dependency_add
        from yoke_core.domain.item_dependency_enrich import cmd_dependency_enrich
        insert_item(test_db, id=100, title="Blocker item")
        insert_item(test_db, id=101, title="Dependent item")
        cmd_dependency_add(test_db, "YOK-101", "YOK-100", "operator")
        cmd_dependency_enrich(test_db)
        row = test_db.execute(
            "SELECT rationale FROM item_dependencies WHERE dependent_item_id=101"
        ).fetchone()
        assert "Blocker item" in row[0]
