"""Tests for the post-delivery drift review module."""
import unittest
from typing import Optional

import pytest

from yoke_core.domain import db_backend
from yoke_core.domain.drift_review import (
    DEFAULT_TRIGGER_THRESHOLD,
    DriftReviewResult,
    _get_checkpoint_start,
    _get_delivered_items,
    should_trigger_review,
)
from yoke_core.domain.drift_review_assess import (
    _classify_drift,
    assess_post_delivery_drift,
)
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from runtime.api.test_dependency_schema import PROJECTS_SCHEMA

TEST_ITEM_ID = 42


def _placeholder(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _apply_drift_schema() -> None:
    """``init_test_db`` ``apply_schema`` strategy for the drift-review tests.

    Builds the minimal ``items`` + ``strategy_checkpoints`` +
    ``item_status_transitions`` tables the drift-review queries exercise
    (deliberately NOT the full production schema). Resolves its own
    connection through the backend factory (``YOKE_DB`` on SQLite, the
    repointed per-test ``YOKE_PG_DSN`` on Postgres), so each test gets an
    isolated table set that never collides with the ambient production
    relations on Postgres.
    """
    from runtime.api.fixtures.schema_ddl import apply_fixture_ddl

    conn = db_backend.connect()
    try:
        apply_fixture_ddl(
            conn,
            PROJECTS_SCHEMA + """CREATE TABLE items (
                id INTEGER PRIMARY KEY,
                title TEXT,
                status TEXT DEFAULT 'done',
                priority TEXT DEFAULT 'low',
                project_id INTEGER NOT NULL DEFAULT 1,
                project_sequence INTEGER,
                merged_at TEXT,
                updated_at TEXT
            );
            CREATE TABLE strategy_checkpoints (
                id INTEGER PRIMARY KEY,
                project_id INTEGER NOT NULL,
                kind TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE item_status_transitions (
                id INTEGER PRIMARY KEY,
                item_id INTEGER NOT NULL,
                task_num INTEGER,
                to_status TEXT NOT NULL,
                project_id INTEGER,
                created_at TEXT NOT NULL
            );""",
        )
    finally:
        conn.close()


def _project_id(slug: str) -> int:
    return 2 if slug == "buzz" else 1


def _insert_drift_item(
    conn,
    item_id: int,
    title: str,
    priority: str,
    project: str = "yoke",
    merged_at: Optional[str] = None,
) -> None:
    p = _placeholder(conn)
    columns = "id, title, priority, project_id, project_sequence"
    values = f"{p}, {p}, {p}, {p}, {p}"
    params = [item_id, title, priority, _project_id(project), item_id]
    if merged_at is not None:
        columns += ", merged_at"
        values += f", {p}"
        params.append(merged_at)
    conn.execute(
        f"INSERT INTO items ({columns}) VALUES ({values})",
        tuple(params),
    )


class _DriftDbCase(unittest.TestCase):
    """Base providing a backend-aware per-test drift-review DB.

    The autouse fixture owns the per-test DB lifecycle (a real file on SQLite,
    a disposable per-test database on Postgres dropped on teardown). Subclass
    tests call :meth:`_make_db` for a backend-aware connection to it.
    """

    @pytest.fixture(autouse=True)
    def _drift_db(self, tmp_path):
        with init_test_db(tmp_path, apply_schema=_apply_drift_schema) as db_path:
            self._db_path = db_path
            yield

    def _make_db(self):
        """Backend-aware connection to this test's drift-review DB."""
        return connect_test_db(self._db_path)


class TestShouldTriggerReview(_DriftDbCase):
    """Trigger heuristic tests."""

    def test_empty_delta_no_trigger(self):
        assert should_trigger_review([]) is False

    def test_single_low_no_trigger(self):
        items = [{"id": 1, "priority": "low"}]
        assert should_trigger_review(items, threshold=5) is False

    def test_single_high_immediate_trigger(self):
        items = [{"id": 1, "priority": "high"}]
        assert should_trigger_review(items) is True

    def test_weight_threshold(self):
        items = [
            {"id": 1, "priority": "medium"},  # 2
            {"id": 2, "priority": "medium"},  # 2
            {"id": 3, "priority": "low"},     # 1
        ]
        assert should_trigger_review(items, threshold=5) is True

    def test_below_threshold(self):
        items = [
            {"id": 1, "priority": "low"},   # 1
            {"id": 2, "priority": "low"},   # 1
        ]
        assert should_trigger_review(items, threshold=5) is False


class TestGetCheckpointStart(_DriftDbCase):
    """Checkpoint anchor tests (strategy_checkpoints sourcing)."""

    def _insert_checkpoint(
        self, conn, kind: str, created_at: str, project: str = "yoke",
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
        assert result == "2026-04-01T12:00:00Z"

    def test_drift_review_anchor(self):
        conn = self._make_db()
        self._insert_checkpoint(conn, "drift_review", "2026-04-03T12:00:00Z")
        result = _get_checkpoint_start(conn, "yoke")
        assert result == "2026-04-03T12:00:00Z"

    def test_latest_of_both(self):
        conn = self._make_db()
        self._insert_checkpoint(conn, "strategize", "2026-04-01T12:00:00Z")
        self._insert_checkpoint(conn, "drift_review", "2026-04-03T12:00:00Z")
        result = _get_checkpoint_start(conn, "yoke")
        assert result == "2026-04-03T12:00:00Z"

    def test_project_scoping_by_slug_and_numeric_id(self):
        conn = self._make_db()
        self._insert_checkpoint(conn, "strategize", "2026-04-01T12:00:00Z")
        # Slug scope matches its own project only; the offer dispatch
        # passes numeric project ids and must scope identically.
        assert _get_checkpoint_start(conn, "buzz") is None
        assert _get_checkpoint_start(conn, 1) == "2026-04-01T12:00:00Z"
        assert _get_checkpoint_start(conn, 2) is None


class TestGetDeliveredItems(_DriftDbCase):
    """Delivered delta tests."""

    def test_no_items(self):
        conn = self._make_db()
        result = _get_delivered_items(conn, "yoke", "2026-04-01T00:00:00Z")
        assert result == []

    def test_merged_at_primary(self):
        conn = self._make_db()
        _insert_drift_item(conn, 42, "Test item", "high",
                           merged_at="2026-04-02T12:00:00Z")
        result = _get_delivered_items(conn, "yoke", "2026-04-01T00:00:00Z")
        assert len(result) == 1
        assert result[0]["id"] == 42

    def test_merged_at_before_checkpoint_excluded(self):
        conn = self._make_db()
        _insert_drift_item(conn, 42, "Test item", "high",
                           merged_at="2026-03-30T12:00:00Z")
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
                (TEST_ITEM_ID, task_num, "done", project_id,
                 "2026-04-02T12:00:00Z"),
            )
        result = _get_delivered_items(conn, "yoke", "2026-04-01T00:00:00Z")
        assert result == []


class TestClassifyDrift(_DriftDbCase):
    """Classifier tests."""

    def test_neither(self):
        conn = self._make_db()
        items = [{"id": 1, "title": "Fix typo in readme", "priority": "low", "delivered_at": "2026-04-02T12:00:00Z"}]
        result = _classify_drift(conn, "yoke", items, "2026-04-01T00:00:00Z")
        assert result.classification == "neither"

    def test_frontier_only(self):
        conn = self._make_db()
        items = [{"id": 1, "title": "Update scheduler ranking logic", "priority": "high", "delivered_at": "2026-04-02T12:00:00Z"}]
        result = _classify_drift(conn, "yoke", items, "2026-04-01T00:00:00Z")
        assert result.classification == "frontier_only"

    def test_sml_only(self):
        conn = self._make_db()
        items = [{"id": 1, "title": "Rewrite mission statement in SML", "priority": "high", "delivered_at": "2026-04-02T12:00:00Z"}]
        result = _classify_drift(conn, "yoke", items, "2026-04-01T00:00:00Z")
        assert result.classification == "sml_only"

    def test_both(self):
        conn = self._make_db()
        items = [
            {"id": 1, "title": "Update strategy and frontier ranking", "priority": "high", "delivered_at": "2026-04-02T12:00:00Z"},
        ]
        result = _classify_drift(conn, "yoke", items, "2026-04-01T00:00:00Z")
        assert result.classification == "both"

    def test_result_shape(self):
        conn = self._make_db()
        items = [{"id": 1, "title": "Fix stuff", "priority": "low", "delivered_at": "2026-04-02T12:00:00Z"}]
        result = _classify_drift(conn, "yoke", items, "2026-04-01T00:00:00Z")
        assert isinstance(result, DriftReviewResult)
        assert result.checkpoint_start == "2026-04-01T00:00:00Z"
        assert result.reviewed_through == "2026-04-02T12:00:00Z"
        assert result.delivered_items == ["YOK-1"]

    def test_to_dict(self):
        result = DriftReviewResult(
            classification="neither",
            summary="test",
            checkpoint_start="A",
            reviewed_through="B",
            delivered_items=["YOK-1"],
        )
        d = result.to_dict()
        assert d["classification"] == "neither"
        assert d["delivered_items"] == ["YOK-1"]


class TestAssessPostDeliveryDrift(_DriftDbCase):
    """Integration tests for the full pipeline."""

    def test_no_delivered_items_returns_none(self):
        conn = self._make_db()
        result = assess_post_delivery_drift(conn, "yoke")
        assert result is None

    def test_high_priority_triggers_review(self):
        conn = self._make_db()
        _insert_drift_item(conn, 42, "Update frontier scheduler", "high",
                           merged_at="2026-04-02T12:00:00Z")
        result = assess_post_delivery_drift(conn, "yoke")
        assert result is not None
        assert result.classification == "frontier_only"

    def test_below_threshold_returns_none(self):
        conn = self._make_db()
        _insert_drift_item(conn, 42, "Fix typo", "low",
                           merged_at="2026-04-02T12:00:00Z")
        result = assess_post_delivery_drift(conn, "yoke")
        assert result is None

    def test_project_scoping(self):
        conn = self._make_db()
        _insert_drift_item(conn, 42, "Update frontier scheduler", "high",
                           project="buzz", merged_at="2026-04-02T12:00:00Z")
        # Query for yoke project — should not see buzz items
        result = assess_post_delivery_drift(conn, "yoke")
        assert result is None

    def test_project_scope_list_checks_every_project(self):
        conn = self._make_db()
        _insert_drift_item(conn, 42, "Update frontier scheduler", "high",
                           project="buzz", merged_at="2026-04-02T12:00:00Z")

        result = assess_post_delivery_drift(conn, ["yoke", "buzz"])

        assert result is not None
        assert result.classification == "frontier_only"
        assert result.delivered_items == ["YOK-42"]

    def test_mixed_numeric_and_slug_scope_normalizes_before_classification(self):
        conn = self._make_db()
        _insert_drift_item(
            conn,
            42,
            "Update frontier scheduler",
            "high",
            project="buzz",
            merged_at="2026-04-02T12:00:00Z",
        )

        result = assess_post_delivery_drift(conn, [1, "buzz"])

        assert result is not None
        assert result.classification == "frontier_only"
        assert result.delivered_items == ["YOK-42"]


if __name__ == "__main__":
    unittest.main()
