"""Tests for classify_items section assignment.

Companion to ``test_sections.py``. Covers status routing into the
active / pipeline / backlog / done / freezer / unknown buckets,
priority sorting, project scope filtering, and epic progress
computation.
"""

from __future__ import annotations

from yoke_contracts.board.sections import (
    classify_items,
    precompute_epic_stats,
)
from runtime.api.board.tests.conftest import (
    insert_item,
    insert_task,
)


class TestClassifyItems:
    def test_empty_db(self, test_db):
        result = classify_items(test_db, "yoke")
        for section in (
            "active", "pipeline", "backlog", "blocked", "freezer", "done", "unknown",
        ):
            assert result[section] == []

    def test_blocked_flag_routes_to_blocked_section(self, test_db):
        """/ AC-3b: items with blocked=1 render in the
        blocked section regardless of their preserved lifecycle status."""
        insert_item(test_db, 1, status="implementing")
        insert_item(test_db, 2, status="refined-idea")
        insert_item(test_db, 3, status="idea")
        # Set the flag directly — insert_item doesn't expose it yet through
        # the test helper, but the schema column already exists.
        test_db.execute("UPDATE items SET blocked = 1 WHERE id IN (1, 2)")
        test_db.commit()
        result = classify_items(test_db, "yoke")
        blocked_ids = {r.id for r in result["blocked"]}
        assert "YOK-1" in blocked_ids
        assert "YOK-2" in blocked_ids
        # Lifecycle status is preserved on the row even though it lives in
        # the blocked section.
        for r in result["blocked"]:
            assert r.status in ("implementing", "refined-idea")
        # Item 3 (no flag) stays in its normal section.
        backlog_ids = {r.id for r in result["backlog"]}
        assert "YOK-3" in backlog_ids

    def test_blocked_flag_outranked_by_frozen(self, test_db):
        """When both flags are set, frozen wins."""
        insert_item(test_db, 1, status="implementing")
        test_db.execute(
            "UPDATE items SET blocked = 1, frozen = 1 WHERE id = 1"
        )
        test_db.commit()
        result = classify_items(test_db, "yoke")
        assert any(r.id == "YOK-1" for r in result["freezer"])
        assert all(r.id != "YOK-1" for r in result["blocked"])

    def test_status_classification(self, test_db):
        """All statuses route to correct sections."""
        for i, status in enumerate(
            [
                "implementing",
                "reviewing-implementation",
                "reviewed-implementation",
                "polishing-implementation",
                "implemented",
                "release",
                "blocked",
                "stopped",
                "failed",
            ],
            start=1,
        ):
            insert_item(test_db, i, status=status)

        for i, status in enumerate(["planned", "refined-idea", "planning", "refining-plan"], start=20):
            insert_item(test_db, i, status=status)

        insert_item(test_db, 30, status="idea")
        insert_item(test_db, 40, status="done")
        insert_item(test_db, 41, status="cancelled")
        insert_item(test_db, 50, status="implementing", frozen=1)

        result = classify_items(test_db, "yoke")

        # blocked / stopped / failed render in their own
        # blocked section instead of being folded into Active.
        active_ids = {r.id for r in result["active"]}
        for i in range(1, 7):
            assert f"YOK-{i}" in active_ids

        blocked_ids = {r.id for r in result["blocked"]}
        for i in (7, 8, 9):
            assert f"YOK-{i}" in blocked_ids

        pipeline_ids = {r.id for r in result["pipeline"]}
        for i in range(20, 24):
            assert f"YOK-{i}" in pipeline_ids

        assert len(result["backlog"]) == 1
        assert result["backlog"][0].id == "YOK-30"

        done_ids = {r.id for r in result["done"]}
        assert "YOK-40" in done_ids
        assert "YOK-41" in done_ids

        assert len(result["freezer"]) == 1
        assert result["freezer"][0].id == "YOK-50"

    def test_unknown_status_routing(self, test_db):
        """AC-4: Items with unrecognized statuses go to 'unknown' section."""
        insert_item(test_db, 1, status="novelstatus")
        result = classify_items(test_db, "yoke")
        assert len(result["unknown"]) == 1
        assert result["unknown"][0].id == "YOK-1"

    def test_sorting_active_by_priority(self, test_db):
        insert_item(test_db, 1, status="implementing", priority="low")
        insert_item(test_db, 2, status="implementing", priority="critical")
        insert_item(test_db, 3, status="implementing", priority="high")
        result = classify_items(test_db, "yoke")
        priorities = [r.priority for r in result["active"]]
        assert priorities == ["critical", "high", "low"]

    def test_sorting_ties_fall_back_to_lexicographic_yok_id(self, test_db):
        insert_item(test_db, 784, status="idea", priority="medium", frozen=1)
        insert_item(test_db, 896, status="idea", priority="medium", frozen=1)
        insert_item(test_db, 897, status="idea", priority="medium", frozen=1)
        result = classify_items(test_db, "yoke")
        ids = [r.id for r in result["freezer"]]
        assert ids == ["YOK-784", "YOK-896", "YOK-897"]

    def test_sorting_done_by_updated_at_desc(self, test_db):
        insert_item(test_db, 1, status="done", updated_at="2024-01-01")
        insert_item(test_db, 2, status="done", updated_at="2024-03-01")
        insert_item(test_db, 3, status="done", updated_at="2024-02-01")
        result = classify_items(test_db, "yoke")
        ids = [r.id for r in result["done"]]
        assert ids == ["YOK-2", "YOK-3", "YOK-1"]

    def test_epic_progress_computed(self, test_db):
        insert_item(test_db, 100, status="implementing", type="epic")
        insert_task(test_db, 100, 1, "T1", "done")
        insert_task(test_db, 100, 2, "T2", "implementing")
        result = classify_items(test_db, "yoke")
        epic_items = [r for r in result["active"] if r.id == "YOK-100"]
        assert len(epic_items) == 1
        assert epic_items[0].progress == "1/2 (50%)"

    def test_epic_progress_with_precomputed_stats(self, test_db):
        """classify_items uses precomputed epic_stats when provided."""
        insert_item(test_db, 100, status="implementing", type="epic")
        insert_task(test_db, 100, 1, "T1", "done")
        insert_task(test_db, 100, 2, "T2", "implementing")
        stats = precompute_epic_stats(test_db, "yoke")
        result = classify_items(test_db, "yoke", epic_stats=stats)
        epic_items = [r for r in result["active"] if r.id == "YOK-100"]
        assert len(epic_items) == 1
        assert epic_items[0].progress == "1/2 (50%)"

    def test_project_scope_filter(self, test_db):
        insert_item(test_db, 1, status="implementing", project="yoke")
        insert_item(test_db, 2, status="implementing", project="externalwebapp")
        result = classify_items(test_db, "yoke")
        all_ids = set()
        for items in result.values():
            for item in items:
                all_ids.add(item.id)
        assert "YOK-1" in all_ids
        assert "YOK-2" not in all_ids

    def test_all_scope_renders_bare_public_refs_from_joined_project_rows(self, test_db):
        test_db.execute(
            "UPDATE projects SET public_item_prefix = %s WHERE slug = %s",
            ("TST", "yoke"),
        )
        test_db.execute(
            "UPDATE projects SET public_item_prefix = %s WHERE slug = %s",
            ("EXT", "externalwebapp"),
        )
        test_db.commit()
        insert_item(test_db, 1, status="implementing", project="yoke")
        insert_item(test_db, 2, status="implementing", project="externalwebapp")

        class NoDirectExecuteConnection:
            def __init__(self, conn):
                self.conn = conn

            def cursor(self, *args, **kwargs):
                return self.conn.cursor(*args, **kwargs)

            def execute(self, *args, **kwargs):
                raise AssertionError("classify_items must not do per-item direct lookups")

            def rollback(self):
                return self.conn.rollback()

            def close(self):
                return self.conn.close()

        test_db._conn = NoDirectExecuteConnection(test_db._conn)

        result = classify_items(test_db, "all")
        all_ids = set()
        for items in result.values():
            for item in items:
                all_ids.add(item.id)
        assert "TST-1" in all_ids
        assert "EXT-2" in all_ids

    def test_implemented_in_active_section(self, test_db):
        """AC-3: Items with status=implemented appear in the active section."""
        insert_item(test_db, 1, status="implemented")
        result = classify_items(test_db, "yoke")
        active_ids = {r.id for r in result["active"]}
        assert "YOK-1" in active_ids

    def test_release_in_active_section(self, test_db):
        """AC-3: Items with status=release appear in the active section."""
        insert_item(test_db, 1, status="release")
        result = classify_items(test_db, "yoke")
        active_ids = {r.id for r in result["active"]}
        assert "YOK-1" in active_ids
        item_row = [r for r in result["active"] if r.id == "YOK-1"][0]
        assert item_row.status == "release"

    def test_epic_refined_idea_goes_to_pipeline(self, test_db):
        """AC-11: epic refined-idea -> planning bucket -> pipeline section."""
        insert_item(test_db, 1, status="refined-idea", type="epic")
        result = classify_items(test_db, "yoke")
        pipeline_ids = {r.id for r in result["pipeline"]}
        assert "YOK-1" in pipeline_ids

    def test_issue_refined_idea_goes_to_pipeline(self, test_db):
        """Issue refined-idea -> refined bucket -> pipeline section."""
        insert_item(test_db, 1, status="refined-idea", type="issue")
        result = classify_items(test_db, "yoke")
        pipeline_ids = {r.id for r in result["pipeline"]}
        assert "YOK-1" in pipeline_ids

    def test_epic_planning_goes_to_pipeline(self, test_db):
        """Epic planning -> planning bucket -> pipeline section."""
        insert_item(test_db, 1, status="planning", type="epic")
        result = classify_items(test_db, "yoke")
        pipeline_ids = {r.id for r in result["pipeline"]}
        assert "YOK-1" in pipeline_ids

    def test_epic_plan_drafted_goes_to_pipeline(self, test_db):
        """Epic plan-drafted -> planning bucket -> pipeline section."""
        insert_item(test_db, 1, status="plan-drafted", type="epic")
        result = classify_items(test_db, "yoke")
        pipeline_ids = {r.id for r in result["pipeline"]}
        assert "YOK-1" in pipeline_ids

    def test_epic_reviewing_implementation_goes_to_active(self, test_db):
        """AC-11: epic reviewing-implementation -> implementing bucket -> active section."""
        insert_item(test_db, 1, status="reviewing-implementation", type="epic")
        result = classify_items(test_db, "yoke")
        active_ids = {r.id for r in result["active"]}
        assert "YOK-1" in active_ids

    def test_issue_reviewing_implementation_goes_to_active(self, test_db):
        """Issue reviewing-implementation -> reviewing bucket -> active section."""
        insert_item(test_db, 1, status="reviewing-implementation", type="issue")
        result = classify_items(test_db, "yoke")
        active_ids = {r.id for r in result["active"]}
        assert "YOK-1" in active_ids

    def test_epic_reviewed_implementation_goes_to_active(self, test_db):
        """Epic reviewed-implementation -> reviewing bucket -> active section."""
        insert_item(test_db, 1, status="reviewed-implementation", type="epic")
        result = classify_items(test_db, "yoke")
        active_ids = {r.id for r in result["active"]}
        assert "YOK-1" in active_ids

    def test_issue_reviewed_implementation_goes_to_active(self, test_db):
        """Issue reviewed-implementation -> reviewing bucket -> active section."""
        insert_item(test_db, 1, status="reviewed-implementation", type="issue")
        result = classify_items(test_db, "yoke")
        active_ids = {r.id for r in result["active"]}
        assert "YOK-1" in active_ids
