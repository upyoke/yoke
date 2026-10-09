"""Native delivery facts and project-scoped post-delivery drift review."""

import unittest

from yoke_contracts.timestamps import parse_instant
from yoke_core.domain.drift_review import (
    DriftReviewResult,
    _get_checkpoint_start,
    _get_delivered_items,
)
from yoke_core.domain.drift_review_assess import (
    _classify_drift,
    assess_post_delivery_drift,
)
from runtime.api.fixtures.drift_review import (
    TEST_ITEM_ID,
    _DriftDbCase,
    _insert_drift_item,
    _placeholder,
    _project_id,
)


class TestGetCheckpointStart(_DriftDbCase):
    """Checkpoint anchor tests (strategy_checkpoints sourcing)."""

    def _insert_checkpoint(
        self,
        conn,
        kind: str,
        created_at: str,
        project: str = "yoke",
    ) -> None:
        p = _placeholder(conn)
        conn.execute(
            "INSERT INTO strategy_checkpoints (project_id, kind, created_at)"
            f" VALUES ({p}, {p}, {p})",
            (_project_id(project), kind, created_at),
        )

    def test_no_checkpoints_returns_none(self):
        conn = self._make_db()
        assert _get_checkpoint_start(conn, "yoke") is None

    def test_strategize_anchor(self):
        conn = self._make_db()
        self._insert_checkpoint(conn, "strategize", "2026-04-01T12:00:00Z")
        result = _get_checkpoint_start(conn, "yoke")
        assert result == parse_instant("2026-04-01T12:00:00Z")

    def test_drift_review_anchor(self):
        conn = self._make_db()
        self._insert_checkpoint(conn, "drift_review", "2026-04-03T12:00:00Z")
        result = _get_checkpoint_start(conn, "yoke")
        assert result == parse_instant("2026-04-03T12:00:00Z")

    def test_latest_of_both(self):
        conn = self._make_db()
        self._insert_checkpoint(conn, "strategize", "2026-04-01T12:00:00Z")
        self._insert_checkpoint(conn, "drift_review", "2026-04-03T12:00:00Z")
        result = _get_checkpoint_start(conn, "yoke")
        assert result == parse_instant("2026-04-03T12:00:00Z")

    def test_project_scoping_by_slug_and_numeric_id(self):
        conn = self._make_db()
        self._insert_checkpoint(conn, "strategize", "2026-04-01T12:00:00Z")
        # Slug scope matches its own project only; the offer dispatch
        # passes numeric project ids and must scope identically.
        assert _get_checkpoint_start(conn, "externalwebapp") is None
        assert _get_checkpoint_start(conn, 1) == parse_instant("2026-04-01T12:00:00Z")
        assert _get_checkpoint_start(conn, 2) is None


class TestGetDeliveredItems(_DriftDbCase):
    """Delivered delta tests."""

    def test_no_items(self):
        conn = self._make_db()
        result = _get_delivered_items(conn, "yoke", "2026-04-01T00:00:00Z")
        assert result == []

    def test_merged_at_primary(self):
        conn = self._make_db()
        _insert_drift_item(
            conn, 42, "Test item", "high", merged_at="2026-04-02T12:00:00Z"
        )
        result = _get_delivered_items(conn, "yoke", "2026-04-01T00:00:00Z")
        assert len(result) == 1
        assert result[0]["id"] == 42

    def test_merged_at_before_checkpoint_excluded(self):
        conn = self._make_db()
        _insert_drift_item(
            conn, 42, "Test item", "high", merged_at="2026-03-30T12:00:00Z"
        )
        result = _get_delivered_items(conn, "yoke", "2026-04-01T00:00:00Z")
        assert len(result) == 0

    def test_fallback_transition_row(self):
        conn = self._make_db()
        p = _placeholder(conn)
        # Item with no merged_at
        _insert_drift_item(conn, TEST_ITEM_ID, "Legacy item", "medium")
        conn.execute(
            "INSERT INTO item_status_transitions "
            "(item_id, to_status, project_id, created_at)"
            f" VALUES ({p}, {p}, {p}, {p})",
            (TEST_ITEM_ID, "done", 1, "2026-04-02T12:00:00Z"),
        )
        result = _get_delivered_items(conn, "yoke", "2026-04-01T00:00:00Z")
        assert len(result) == 1
        assert result[0]["id"] == TEST_ITEM_ID

    def test_fallback_ignores_task_transitions_and_other_projects(self):
        conn = self._make_db()
        p = _placeholder(conn)
        _insert_drift_item(conn, TEST_ITEM_ID, "Legacy item", "medium")
        # A task-level done (task_num set) is not an item delivery, and an
        # other-project delivery must not leak into the yoke scope.
        for task_num, project_id in ((3, 1), (None, 2)):
            conn.execute(
                "INSERT INTO item_status_transitions "
                "(item_id, task_num, to_status, project_id, created_at)"
                f" VALUES ({p}, {p}, {p}, {p}, {p})",
                (TEST_ITEM_ID, task_num, "done", project_id, "2026-04-02T12:00:00Z"),
            )
        result = _get_delivered_items(conn, "yoke", "2026-04-01T00:00:00Z")
        assert result == []


class TestClassifyDrift(_DriftDbCase):
    """Classifier tests."""

    def test_neither(self):
        conn = self._make_db()
        items = [
            {
                "id": 1,
                "title": "Fix typo in readme",
                "priority": "low",
                "delivered_at": "2026-04-02T12:00:00Z",
            }
        ]
        result = _classify_drift(conn, "yoke", items, "2026-04-01T00:00:00Z")
        assert result.classification == "neither"

    def test_frontier_only(self):
        conn = self._make_db()
        items = [
            {
                "id": 1,
                "title": "Update scheduler ranking logic",
                "priority": "high",
                "delivered_at": "2026-04-02T12:00:00Z",
            }
        ]
        result = _classify_drift(conn, "yoke", items, "2026-04-01T00:00:00Z")
        assert result.classification == "frontier_only"

    def test_sml_only(self):
        conn = self._make_db()
        items = [
            {
                "id": 1,
                "title": "Rewrite mission statement in SML",
                "priority": "high",
                "delivered_at": "2026-04-02T12:00:00Z",
            }
        ]
        result = _classify_drift(conn, "yoke", items, "2026-04-01T00:00:00Z")
        assert result.classification == "sml_only"

    def test_both(self):
        conn = self._make_db()
        items = [
            {
                "id": 1,
                "title": "Update strategy and frontier ranking",
                "priority": "high",
                "delivered_at": "2026-04-02T12:00:00Z",
            },
        ]
        result = _classify_drift(conn, "yoke", items, "2026-04-01T00:00:00Z")
        assert result.classification == "both"

    def test_result_shape(self):
        conn = self._make_db()
        # The delivered item is named by its own sequence, which here is
        # deliberately not its internal id: a result built from the id would
        # list whichever other item owns that number.
        internal_id, sequence = 1, 604
        _insert_drift_item(
            conn,
            internal_id,
            "Fix stuff",
            "low",
            merged_at="2026-04-02T12:00:00Z",
            project_sequence=sequence,
        )
        items = [
            {
                "id": internal_id,
                "title": "Fix stuff",
                "priority": "low",
                "delivered_at": "2026-04-02T12:00:00Z",
            }
        ]
        result = _classify_drift(conn, "yoke", items, "2026-04-01T00:00:00Z")
        assert isinstance(result, DriftReviewResult)
        assert result.checkpoint_start == parse_instant("2026-04-01T00:00:00Z")
        assert result.reviewed_through == parse_instant("2026-04-02T12:00:00Z")
        assert result.delivered_items == [f"YOK-{sequence}"]

    def test_to_dict(self):
        result = DriftReviewResult(
            classification="neither",
            summary="test",
            checkpoint_start="2026-04-01T00:00:00.000001Z",
            reviewed_through="2026-04-02T12:00:00.000002Z",
            delivered_items=["YOK-1"],
        )
        d = result.to_dict()
        assert d["classification"] == "neither"
        assert d["checkpoint_start"] == "2026-04-01T00:00:00.000001Z"
        assert d["reviewed_through"] == "2026-04-02T12:00:00.000002Z"
        assert d["delivered_items"] == ["YOK-1"]


class TestAssessPostDeliveryDrift(_DriftDbCase):
    """Integration tests for the full pipeline."""

    def test_no_delivered_items_returns_none(self):
        conn = self._make_db()
        result = assess_post_delivery_drift(conn, "yoke")
        assert result is None

    def test_high_priority_triggers_review(self):
        conn = self._make_db()
        _insert_drift_item(
            conn,
            42,
            "Update frontier scheduler",
            "high",
            merged_at="2026-04-02T12:00:00Z",
        )
        result = assess_post_delivery_drift(conn, "yoke")
        assert result is not None
        assert result.classification == "frontier_only"

    def test_below_threshold_returns_none(self):
        conn = self._make_db()
        _insert_drift_item(
            conn, 42, "Fix typo", "low", merged_at="2026-04-02T12:00:00Z"
        )
        result = assess_post_delivery_drift(conn, "yoke")
        assert result is None

    def test_project_scoping(self):
        conn = self._make_db()
        _insert_drift_item(
            conn,
            42,
            "Update frontier scheduler",
            "high",
            project="externalwebapp",
            merged_at="2026-04-02T12:00:00Z",
        )
        # Query for yoke project — should not see externalwebapp items
        result = assess_post_delivery_drift(conn, "yoke")
        assert result is None

    def test_project_scope_list_checks_every_project(self):
        conn = self._make_db()
        _insert_drift_item(
            conn,
            42,
            "Update frontier scheduler",
            "high",
            project="externalwebapp",
            merged_at="2026-04-02T12:00:00Z",
        )

        result = assess_post_delivery_drift(conn, ["yoke", "externalwebapp"])

        assert result is not None
        assert result.classification == "frontier_only"
        assert result.delivered_items == ["EXT-42"]

    def test_mixed_numeric_and_slug_scope_normalizes_before_classification(self):
        conn = self._make_db()
        _insert_drift_item(
            conn,
            42,
            "Update frontier scheduler",
            "high",
            project="externalwebapp",
            merged_at="2026-04-02T12:00:00Z",
        )

        result = assess_post_delivery_drift(conn, [1, "externalwebapp"])

        assert result is not None
        assert result.classification == "frontier_only"
        assert result.delivered_items == ["EXT-42"]


if __name__ == "__main__":
    unittest.main()
