"""Tests for frontier_counts + consistency_check.

Companion to ``test_sections.py``. Covers the dashboard-aggregation
helpers that drive the board frontier widget and the row-count audit
that catches truncated renders.
"""

from __future__ import annotations

from yoke_contracts.board.sections import (
    consistency_check,
    frontier_counts,
)
from runtime.api.board.tests.conftest import (
    insert_item,
    insert_task,
)


class TestFrontierCounts:
    def test_empty_db(self, test_db):
        result = frontier_counts(test_db, "yoke")
        assert result["total"] == 0

    def test_simple_counts(self, test_db):
        insert_item(test_db, 1, status="done")
        insert_item(test_db, 2, status="implementing")
        insert_item(test_db, 3, status="idea")
        insert_item(test_db, 4, status="blocked")
        insert_item(test_db, 5, status="reviewing-implementation", type="issue")
        insert_item(test_db, 6, status="planned")
        result = frontier_counts(test_db, "yoke")
        assert result["done"] == 1
        assert result["implementing"] == 1
        assert result["idea"] == 1
        assert result["blocked"] == 1
        assert result["reviewing"] == 1
        assert result["refined"] == 1
        assert result["total"] == 6

    def test_frozen_excluded(self, test_db):
        insert_item(test_db, 1, status="implementing")
        insert_item(test_db, 2, status="implementing", frozen=1)
        result = frontier_counts(test_db, "yoke")
        assert result["implementing"] == 1
        assert result["total"] == 1

    def test_task_expanded(self, test_db):
        insert_item(test_db, 10, status="implementing", type="epic")
        insert_task(test_db, 10, 1, "T1", "done")
        insert_task(test_db, 10, 2, "T2", "implementing")
        result = frontier_counts(test_db, "yoke")
        assert result["done"] == 1
        assert result["implementing"] == 1
        assert result["total"] == 2

    def test_art_frontier_since_filter(self, test_db):
        insert_item(test_db, 1, status="done")
        insert_item(test_db, 100, status="implementing")
        result = frontier_counts(test_db, "yoke", art_frontier_since=50)
        assert result["implementing"] == 1
        assert result["done"] == 0
        assert result["total"] == 1

    def test_cancelled_excluded(self, test_db):
        insert_item(test_db, 1, status="cancelled")
        result = frontier_counts(test_db, "yoke")
        assert result["done"] == 0
        assert result["total"] == 0

    def test_implementing_counts_as_implementing(self, test_db):
        insert_item(test_db, 1, status="implementing")
        result = frontier_counts(test_db, "yoke")
        assert result["implementing"] == 1

    def test_stopped_counts_as_blocked(self, test_db):
        insert_item(test_db, 1, status="stopped")
        result = frontier_counts(test_db, "yoke")
        assert result["blocked"] == 1

    def test_pipeline_statuses_count_as_refined(self, test_db):
        insert_item(test_db, 1, status="planned")
        insert_item(test_db, 2, status="refined-idea", type="issue")
        insert_item(test_db, 3, status="planned")
        result = frontier_counts(test_db, "yoke")
        assert result["refined"] == 3

    def test_planning_counts_as_planning(self, test_db):
        """Epic-workflow-type planning status counts in planning bucket."""
        insert_item(test_db, 1, status="planning")
        result = frontier_counts(test_db, "yoke")
        assert result["planning"] == 1

    def test_plan_drafted_counts_as_planning(self, test_db):
        """Epic-workflow-type plan-drafted status counts in planning bucket."""
        insert_item(test_db, 1, status="plan-drafted")
        result = frontier_counts(test_db, "yoke")
        assert result["planning"] == 1

    def test_refining_plan_counts_as_planning(self, test_db):
        """Epic-workflow-type refining-plan status counts in planning bucket."""
        insert_item(test_db, 1, status="refining-plan")
        result = frontier_counts(test_db, "yoke")
        assert result["planning"] == 1

    def test_refining_idea_counts_as_planning(self, test_db):
        """Issue-workflow-type refining-idea still counts in planning bucket."""
        insert_item(test_db, 1, status="refining-idea")
        result = frontier_counts(test_db, "yoke")
        assert result["planning"] == 1

    def test_epic_refined_idea_counts_as_planning(self, test_db):
        """Epic refined-idea uses the planning bucket in aggregate counts."""
        insert_item(test_db, 1, status="refined-idea", type="epic")
        result = frontier_counts(test_db, "yoke")
        assert result["planning"] == 1
        assert result["refined"] == 0

    def test_issue_refined_idea_counts_as_refined(self, test_db):
        """Issue refined-idea stays in the refined bucket in aggregate counts."""
        insert_item(test_db, 1, status="refined-idea", type="issue")
        result = frontier_counts(test_db, "yoke")
        assert result["refined"] == 1
        assert result["planning"] == 0

    def test_epic_reviewing_implementation_counts_as_implementing(self, test_db):
        """Epic reviewing-implementation stays in implementing aggregate counts."""
        insert_item(test_db, 1, status="reviewing-implementation", type="epic")
        result = frontier_counts(test_db, "yoke")
        assert result["implementing"] == 1
        assert result["reviewing"] == 0

    def test_issue_reviewing_implementation_counts_as_reviewing(self, test_db):
        """Issue reviewing-implementation stays in reviewing aggregate counts."""
        insert_item(test_db, 1, status="reviewing-implementation", type="issue")
        result = frontier_counts(test_db, "yoke")
        assert result["reviewing"] == 1
        assert result["implementing"] == 0

    def test_epic_reviewed_implementation_counts_as_reviewing(self, test_db):
        """Epic reviewed-implementation stays in reviewing aggregate counts."""
        insert_item(test_db, 1, status="reviewed-implementation", type="epic")
        result = frontier_counts(test_db, "yoke")
        assert result["reviewing"] == 1
        assert result["implementing"] == 0

    def test_issue_reviewed_implementation_counts_as_reviewing(self, test_db):
        """Issue reviewed-implementation stays in reviewing aggregate counts."""
        insert_item(test_db, 1, status="reviewed-implementation", type="issue")
        result = frontier_counts(test_db, "yoke")
        assert result["reviewing"] == 1
        assert result["implementing"] == 0


class TestConsistencyCheck:
    def test_matching_counts(self):
        content = (
            "| YOK-1 | done |\n"
            "| | done | | | task | | └ 001: T1 |\n"
            "| | implementing | | | task | | └ 002: T2 |"
        )
        ok, msg = consistency_check(2, content)
        assert ok is True
        assert "OK" in msg

    def test_mismatch(self):
        content = "| YOK-1 | done |\n| | done | | | task | | └ 001: T1 |"
        ok, msg = consistency_check(3, content)
        assert ok is False
        assert "mismatch" in msg

    def test_zero_expected_zero_found(self):
        content = "| YOK-1 | done |"
        ok, msg = consistency_check(0, content)
        assert ok is True
