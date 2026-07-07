"""Review and simulation tests for ``yoke_core.domain.epic``.

Split from ``test_epic_full.py``.

Uses the shared ``test_db`` fixture from ``conftest.py``.
"""

from __future__ import annotations

import json

import pytest

from yoke_core.domain import epic
from runtime.api.conftest import insert_qa_requirement, insert_qa_run


class TestReviewGet:
    def test_review_get_no_review(self, test_db):
        epic.task_upsert(test_db, "42", 1, "Widget", "", "", "")
        with pytest.raises(LookupError, match="no review found"):
            epic.review_get(test_db, "42", 1)

    def test_review_get_with_data(self, test_db):
        """Insert review data directly (bypassing subprocess) to test read path."""
        epic.task_upsert(test_db, "42", 1, "Widget", "", "", "")
        req = insert_qa_requirement(
            test_db,
            item_id=None,
            epic_id=42,
            task_num=1,
            qa_kind="implementation_review",
            qa_phase="verification",
        )
        raw_result = json.dumps({"body": "Looks good"})
        insert_qa_run(
            test_db,
            qa_requirement_id=req["id"],
            executor_type="agent",
            qa_kind="implementation_review",
            verdict="pass",
            raw_result=raw_result,
        )

        result = epic.review_get(test_db, "42", 1)
        assert "PASS" in result
        assert "Looks good" in result

    def test_review_get_fail_verdict(self, test_db):
        epic.task_upsert(test_db, "42", 1, "Widget", "", "", "")
        req = insert_qa_requirement(
            test_db,
            item_id=None,
            epic_id=42,
            task_num=1,
            qa_kind="implementation_review",
            qa_phase="verification",
        )
        raw_result = json.dumps({"body": "Needs work"})
        insert_qa_run(
            test_db,
            qa_requirement_id=req["id"],
            executor_type="agent",
            qa_kind="implementation_review",
            verdict="fail",
            raw_result=raw_result,
        )

        result = epic.review_get(test_db, "42", 1)
        assert "FAIL" in result
        assert "Needs work" in result


class TestSimulationParsing:
    """Test _parse_simulation_result matching all shell test cases."""

    def test_result_clean(self):
        body = "## Result: CLEAN\nAll good."
        assert epic._parse_simulation_result(body) == "CLEAN"

    def test_result_gaps_found(self):
        body = "## Result: GAPS FOUND\nSome issues."
        assert epic._parse_simulation_result(body) == "GAPS FOUND"

    def test_result_gaps_found_suffix(self):
        body = "## Result: GAPS FOUND (all fixed in cycle 1)\nDetails."
        assert epic._parse_simulation_result(body) == "GAPS FOUND"

    def test_result_count_format_gaps(self):
        body = "## Result: 3 critical, 2 warnings, 1 notes"
        assert epic._parse_simulation_result(body) == "GAPS FOUND"

    def test_result_count_format_clean(self):
        body = "## Result: 0 critical, 0 warnings, 0 notes"
        assert epic._parse_simulation_result(body) == "CLEAN"

    def test_bold_format(self):
        body = "**Result:** 1 gap found\nDetails."
        assert epic._parse_simulation_result(body) == "GAPS FOUND"

    def test_simulation_prefix_clean(self):
        body = "SIMULATION: CLEAN\nAll good."
        assert epic._parse_simulation_result(body) == "CLEAN"

    def test_simulation_prefix_gaps_found(self):
        body = "SIMULATION: GAPS FOUND\n## Gap 1: Missing interface"
        assert epic._parse_simulation_result(body) == "GAPS FOUND"

    def test_simulation_prefix_takes_priority(self):
        """SIMULATION: prefix overrides ## Result: line."""
        body = "SIMULATION: GAPS FOUND\n## Result: CLEAN\nContradiction."
        assert epic._parse_simulation_result(body) == "GAPS FOUND"

    def test_clean_with_suffix(self):
        body = "SIMULATION: CLEAN -- No issues found."
        assert epic._parse_simulation_result(body) == "CLEAN"

    def test_no_result_returns_none(self):
        body = "No result line here, just notes about the simulation."
        assert epic._parse_simulation_result(body) is None

    def test_empty_body_returns_none(self):
        assert epic._parse_simulation_result("") is None

    def test_incidental_clean_in_prose_rejected(self):
        """incidental 'clean' in prose should not match."""
        body = "The integration looks clean overall. No issues observed during testing."
        assert epic._parse_simulation_result(body) is None

    def test_truncated_output_rejected(self):
        """truncated output without proper format."""
        body = "Let me check the integration paths...\nStatus: reviewing code for issues"
        assert epic._parse_simulation_result(body) is None

    def test_simulation_clean_prefix_parses(self):
        """positive control: SIMULATION: CLEAN."""
        body = "SIMULATION: CLEAN\n\nAll integrations verified."
        assert epic._parse_simulation_result(body) == "CLEAN"

    def test_clean_in_prose_not_prefix(self):
        """CLEAN in prose body but not as prefix."""
        body = "The code is not CLEAN enough to pass without further review.\n## Other section"
        assert epic._parse_simulation_result(body) is None

    def test_simulation_gaps_found_prefix_parses(self):
        """positive control: SIMULATION: GAPS FOUND."""
        body = "SIMULATION: GAPS FOUND\n### GAP #1: Missing error handler"
        assert epic._parse_simulation_result(body) == "GAPS FOUND"


class TestSimulationGet:
    def test_simulation_get(self, test_db):
        """Directly insert simulation data, then read with simulation_get."""
        # Insert requirement and run for simulation
        req = insert_qa_requirement(
            test_db,
            item_id=42,
            epic_id=None,
            task_num=None,
            qa_kind="simulation",
            qa_phase="verification",
            success_policy='{"type":"deterministic","criteria":"result_pass","phase":"plan"}',
        )
        # Use compact JSON (no spaces) to match the LIKE query in simulation_get
        raw_result = json.dumps(
            {"body": "SIMULATION: CLEAN\nAll good.", "phase": "plan"},
            separators=(",", ":"),
        )
        insert_qa_run(
            test_db,
            qa_requirement_id=req["id"],
            executor_type="agent",
            qa_kind="simulation",
            verdict="pass",
            raw_result=raw_result,
        )

        result = epic.simulation_get(test_db, "42", "plan")
        assert "plan" in result
        assert "CLEAN" in result
        # Pipe-delimited: id|item_id|phase|result|body|created_at => 5 pipes
        assert result.count("|") == 5

    def test_simulation_get_not_found(self, test_db):
        with pytest.raises(LookupError, match="not found"):
            epic.simulation_get(test_db, "42", "nonexistent")

    def test_simulation_get_gaps_found(self, test_db):
        req = insert_qa_requirement(
            test_db,
            item_id=42,
            epic_id=None,
            task_num=None,
            qa_kind="simulation",
            qa_phase="verification",
            success_policy='{"type":"deterministic","criteria":"result_pass","phase":"integration"}',
        )
        raw_result = json.dumps(
            {"body": "SIMULATION: GAPS FOUND\n## Gap 1: Missing interface", "phase": "integration"},
            separators=(",", ":"),
        )
        insert_qa_run(
            test_db,
            qa_requirement_id=req["id"],
            executor_type="agent",
            qa_kind="simulation",
            verdict="fail",
            raw_result=raw_result,
        )

        result = epic.simulation_get(test_db, "42", "integration")
        assert "GAPS FOUND" in result
        assert "integration" in result
