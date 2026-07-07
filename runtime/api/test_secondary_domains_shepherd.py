"""Tests for yoke_core.domain.shepherd."""
from __future__ import annotations

import pytest

from runtime.api.conftest import insert_item


TEST_ITEM_ID = 42
TEST_ITEM_REF = f"YOK-{TEST_ITEM_ID}"


class TestShepherd:
    def test_verdict(self, test_db):
        from yoke_core.domain.shepherd import cmd_verdict
        rid = cmd_verdict(test_db, TEST_ITEM_REF, "refined_to_planned", "boss", "READY")
        assert rid.isdigit()

    def test_shepherd_log(self, test_db):
        from yoke_core.domain.shepherd import cmd_shepherd_log, cmd_verdict
        cmd_verdict(test_db, "YOK-10", "t1", "boss", "READY")
        cmd_verdict(test_db, "YOK-10", "t2", "boss", "CAVEATS", "caveat1\ncaveat2")
        log = cmd_shepherd_log(test_db, "YOK-10")
        assert "## Shepherd Log" in log
        assert "READY" in log
        assert "CAVEATS" in log

    def test_caveat_disposition(self, test_db):
        from yoke_core.domain.shepherd import cmd_caveat_disposition, cmd_caveat_dispositions
        cmd_caveat_disposition(
            test_db, "YOK-5", "t1", 1, 1,
            "Missing tests", "RESOLVED", "Tests added",
        )
        result = cmd_caveat_dispositions(test_db, "YOK-5")
        assert "RESOLVED" in result
        assert "Missing tests" in result

    def test_dependency_add_and_list(self, test_db):
        from yoke_core.domain.shepherd import cmd_dependency_add, cmd_dependency_list
        cmd_dependency_add(test_db, "YOK-10", "YOK-5", "operator")
        result = cmd_dependency_list(test_db, "YOK-10")
        assert "depends-on" in result
        assert "YOK-5" in result

    def test_dependency_remove(self, test_db):
        from yoke_core.domain.shepherd import (
            cmd_dependency_add,
            cmd_dependency_list,
            cmd_dependency_remove,
        )
        cmd_dependency_add(test_db, "YOK-10", "YOK-5", "operator")
        cmd_dependency_remove(test_db, "YOK-10", "YOK-5")
        result = cmd_dependency_list(test_db, "YOK-10")
        assert result == ""

    def test_dependency_update(self, test_db):
        from yoke_core.domain.shepherd import cmd_dependency_add, cmd_dependency_update
        cmd_dependency_add(test_db, "YOK-20", "YOK-15", "shepherd",
                           gate_point="activation")
        cmd_dependency_update(test_db, "YOK-20", "YOK-15",
                              rationale="Updated rationale")

    def test_invalid_gate_point(self, test_db):
        from yoke_core.domain.shepherd import cmd_dependency_add
        with pytest.raises(ValueError, match="gate_point"):
            cmd_dependency_add(test_db, "YOK-1", "YOK-2", "operator",
                               gate_point="bogus")

    def test_invalid_source(self, test_db):
        from yoke_core.domain.shepherd import cmd_dependency_add
        with pytest.raises(ValueError, match="source"):
            cmd_dependency_add(test_db, "YOK-1", "YOK-2", "unknown_source")

    def test_dependency_enrich(self, test_db):
        from yoke_core.domain.shepherd import cmd_dependency_add, cmd_dependency_enrich
        insert_item(test_db, id=100, title="Blocker item")
        insert_item(test_db, id=101, title="Dependent item")
        cmd_dependency_add(test_db, "YOK-101", "YOK-100", "operator")
        cmd_dependency_enrich(test_db)
        # Verify rationale was enriched
        row = test_db.execute(
            "SELECT rationale FROM item_dependencies WHERE dependent_item='YOK-101'"
        ).fetchone()
        assert "Blocker item" in row[0]
