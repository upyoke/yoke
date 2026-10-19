"""Tests for yoke_core.domain.shepherd."""
from __future__ import annotations


TEST_ITEM_ID = 42
TEST_ITEM_REF = f"YOK-{TEST_ITEM_ID}"


class TestShepherd:
    def test_verdict(self, test_db):
        from yoke_core.domain.shepherd import cmd_verdict
        rid = cmd_verdict(test_db, TEST_ITEM_REF, "refined_to_planned", "boss", "READY")
        assert rid.isdigit()

    def test_verdict_log(self, test_db):
        from yoke_core.domain.shepherd import cmd_verdict, cmd_verdict_log
        cmd_verdict(test_db, "YOK-10", "t1", "boss", "READY")
        cmd_verdict(test_db, "YOK-10", "t2", "boss", "CAVEATS", "caveat1\ncaveat2")
        log = cmd_verdict_log(test_db, "YOK-10")
        assert "## Shepherd Log" in log
        assert "READY" in log
        assert "CAVEATS" in log

    def test_item_verdicts_newest_first(self, test_db):
        from yoke_core.domain.shepherd import cmd_verdict
        from yoke_core.domain.shepherd_verdict_log import item_verdicts
        cmd_verdict(test_db, "YOK-11", "t1", "boss", "READY")
        cmd_verdict(test_db, "YOK-11", "t2", "boss", "CAVEATS", "caveat1")
        verdicts = item_verdicts(test_db, "YOK-11")
        assert [v["transition"] for v in verdicts] == ["t2", "t1"]
        assert verdicts[0]["verdict"] == "CAVEATS"
        assert verdicts[0]["caveats"] == "caveat1"
        assert verdicts[0]["worker"] == "boss"
        assert verdicts[0]["attempt"] == 1
        assert verdicts[0]["created_at"]
        assert item_verdicts(test_db, "YOK-12") == []

    def test_caveat_disposition(self, test_db):
        from yoke_core.domain.shepherd import cmd_caveat_disposition, cmd_caveat_dispositions
        cmd_caveat_disposition(
            test_db, "YOK-5", "t1", 1, 1,
            "Missing tests", "RESOLVED", "Tests added",
        )
        result = cmd_caveat_dispositions(test_db, "YOK-5")
        assert "RESOLVED" in result
        assert "Missing tests" in result
