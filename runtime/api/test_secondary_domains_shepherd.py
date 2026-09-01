"""Tests for yoke_core.domain.shepherd."""
from __future__ import annotations


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
