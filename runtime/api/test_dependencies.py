"""Tests for yoke_core.domain.dependencies — first-class dependency gates.

Covers:
- Enum resolution from DB values
- Satisfaction evaluation for status:done, status:implemented, fact:merged
- Gate-point-aware dependency queries
- Frontier batch query
- Human-readable explanation generation
- Legacy migration value computation
"""

from __future__ import annotations

import os
import sys
from typing import Any

import pytest

# Ensure the repo root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from runtime.api.test_dependency_schema import create_dependency_test_db
from yoke_core.domain.dependencies import (
    DependencyEdge,
    GatePoint,
    GateResult,
    Satisfaction,
    evaluate_satisfaction,
    query_frontier_blocks,
    query_unsatisfied_at_gate,
)


TEST_ITEM_ID = 4242
TEST_ITEM_REF = f"YOK-{TEST_ITEM_ID}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_test_db() -> Any:
    """Create a disposable DB with minimal schema."""
    return create_dependency_test_db()


def _insert_item(conn, item_id, title="", status="idea", worktree=None):
    if not title:
        title = f"Item {item_id}"
    _now = "2026-01-01T00:00:00Z"
    conn.execute(
        "INSERT INTO items (id, title, status, worktree, created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s)",
        (item_id, title, status, worktree, _now, _now),
    )


def _insert_dep(conn, dependent, blocking,
                gate_point="activation", satisfaction="status:done"):
    conn.execute(
        "INSERT INTO item_dependencies "
        "(dependent_item, blocking_item, gate_point, satisfaction, source, created_at) "
        "VALUES (%s, %s, %s, %s, 'test', '2026-01-01T00:00:00Z')",
        (dependent, blocking, gate_point, satisfaction),
    )


# ---------------------------------------------------------------------------
# Enum tests
# ---------------------------------------------------------------------------


class TestEnums:
    """Enum resolution from DB values."""

    def test_gate_point_from_db(self):
        assert GatePoint.from_db("activation") == GatePoint.ACTIVATION
        assert GatePoint.from_db("integration") == GatePoint.INTEGRATION
        assert GatePoint.from_db("closure") == GatePoint.CLOSURE

    def test_gate_point_from_db_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown gate_point"):
            GatePoint.from_db("nonexistent")

    def test_satisfaction_from_db(self):
        assert Satisfaction.from_db("status:done") == Satisfaction.STATUS_DONE
        assert (
            Satisfaction.from_db("status:implemented")
            == Satisfaction.STATUS_IMPLEMENTED
        )
        assert Satisfaction.from_db("fact:merged") == Satisfaction.FACT_MERGED

    def test_satisfaction_from_db_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown satisfaction"):
            Satisfaction.from_db("nonexistent")

    def test_enum_values_are_strings(self):
        """Enum values must be usable as DB strings."""
        assert GatePoint.ACTIVATION.value == "activation"
        assert Satisfaction.STATUS_DONE.value == "status:done"


# ---------------------------------------------------------------------------
# Satisfaction evaluation tests
# ---------------------------------------------------------------------------


class TestEvaluateSatisfaction:
    """Satisfaction condition evaluation."""

    # --- status:done ---

    def test_status_done_satisfied(self):
        result = evaluate_satisfaction("status:done", "done")
        assert result.satisfied is True

    def test_status_done_not_satisfied(self):
        for status in ("idea", "implementing", "reviewing-implementation", "implemented", "release"):
            result = evaluate_satisfaction("status:done", status)
            assert result.satisfied is False, f"status={status} should not satisfy status:done"

    # --- status:implemented ---

    def test_status_implemented_satisfied_by_implemented(self):
        result = evaluate_satisfaction("status:implemented", "implemented")
        assert result.satisfied is True

    def test_status_implemented_satisfied_by_release(self):
        result = evaluate_satisfaction("status:implemented", "release")
        assert result.satisfied is True

    def test_status_implemented_satisfied_by_done(self):
        result = evaluate_satisfaction("status:implemented", "done")
        assert result.satisfied is True

    def test_status_implemented_not_satisfied(self):
        for status in ("idea", "implementing", "reviewing-implementation"):
            result = evaluate_satisfaction("status:implemented", status)
            assert result.satisfied is False

    # --- fact:merged ---

    def test_fact_merged_satisfied_by_explicit_flag(self):
        result = evaluate_satisfaction(
            "fact:merged",
            "implementing",
            TEST_ITEM_REF,
            blocking_merged=True,
        )
        assert result.satisfied is True

    def test_fact_merged_not_satisfied_by_explicit_flag(self):
        result = evaluate_satisfaction(
            "fact:merged",
            "implementing",
            TEST_ITEM_REF,
            blocking_merged=False,
        )
        assert result.satisfied is False

    def test_fact_merged_fallback_release_status(self):
        """When blocking_merged is None, release/done status implies merge."""
        result = evaluate_satisfaction("fact:merged", "release")
        assert result.satisfied is True

    def test_fact_merged_fallback_done_status(self):
        result = evaluate_satisfaction("fact:merged", "done")
        assert result.satisfied is True

    def test_fact_merged_fallback_implementing_not_satisfied(self):
        result = evaluate_satisfaction("fact:merged", "implementing")
        assert result.satisfied is False

    # --- unknown ---

    def test_unknown_satisfaction_fails_safe(self):
        result = evaluate_satisfaction("unknown:condition", "done")
        assert result.satisfied is False

    # --- reasons ---

    def test_reason_contains_status(self):
        result = evaluate_satisfaction("status:done", "implementing")
        assert "implementing" in result.reason


# ---------------------------------------------------------------------------
# Gate-point query tests
# ---------------------------------------------------------------------------


class TestQueryUnsatisfiedAtGate:
    """Gate-point-aware dependency queries."""

    def test_no_dependencies(self):
        conn = _create_test_db()
        _insert_item(conn, 1)
        results = query_unsatisfied_at_gate(conn, "YOK-1", "activation")
        assert results == []

    def test_satisfied_dependency_not_returned(self):
        conn = _create_test_db()
        _insert_item(conn, 1)
        _insert_item(conn, 2, status="done")
        _insert_dep(conn, "YOK-1", "YOK-2", gate_point="activation", satisfaction="status:done")
        results = query_unsatisfied_at_gate(conn, "YOK-1", "activation")
        assert results == []

    def test_unsatisfied_dependency_returned(self):
        conn = _create_test_db()
        _insert_item(conn, 1)
        _insert_item(conn, 2, status="implementing")
        _insert_dep(conn, "YOK-1", "YOK-2", gate_point="activation", satisfaction="status:done")
        results = query_unsatisfied_at_gate(conn, "YOK-1", "activation")
        assert len(results) == 1
        edge, gate_result = results[0]
        assert edge.blocking_item == "YOK-2"
        assert gate_result.satisfied is False

    def test_gate_point_filter(self):
        """Only return deps matching the requested gate point."""
        conn = _create_test_db()
        _insert_item(conn, 1)
        _insert_item(conn, 2, status="implementing")
        _insert_item(conn, 3, status="implementing")
        _insert_dep(conn, "YOK-1", "YOK-2", gate_point="activation", satisfaction="status:done")
        _insert_dep(conn, "YOK-1", "YOK-3", gate_point="integration", satisfaction="fact:merged")
        # Only activation gate
        results = query_unsatisfied_at_gate(conn, "YOK-1", "activation")
        assert len(results) == 1
        assert results[0][0].blocking_item == "YOK-2"
        # Only integration gate
        results = query_unsatisfied_at_gate(conn, "YOK-1", "integration")
        assert len(results) == 1
        assert results[0][0].blocking_item == "YOK-3"

    def test_fact_merged_satisfied_by_merged_at(self):
        conn = _create_test_db()
        _insert_item(conn, 1)
        _insert_item(conn, 2, status="implementing")
        conn.execute(
            "UPDATE items SET merged_at = '2026-01-02T00:00:00Z' WHERE id = 2"
        )
        _insert_dep(conn, "YOK-1", "YOK-2", gate_point="integration", satisfaction="fact:merged")
        results = query_unsatisfied_at_gate(conn, "YOK-1", "integration")
        assert results == []



# ---------------------------------------------------------------------------
# Frontier blocks query tests
# ---------------------------------------------------------------------------


class TestQueryFrontierBlocks:
    """Batch frontier blocking query."""

    def test_empty_frontier(self):
        conn = _create_test_db()
        blocks = query_frontier_blocks(conn, "activation")
        assert blocks == {}

    def test_unsatisfied_blockers_returned(self):
        conn = _create_test_db()
        _insert_item(conn, 1)
        _insert_item(conn, 2, status="implementing")
        _insert_dep(conn, "YOK-1", "YOK-2", gate_point="activation", satisfaction="status:done")
        blocks = query_frontier_blocks(conn, "activation")
        assert "YOK-1" in blocks
        assert len(blocks["YOK-1"]) == 1
        blk_item, blk_status, sat, reason = blocks["YOK-1"][0]
        assert blk_item == "YOK-2"
        assert blk_status == "implementing"

    def test_satisfied_blockers_excluded(self):
        conn = _create_test_db()
        _insert_item(conn, 1)
        _insert_item(conn, 2, status="done")
        _insert_dep(conn, "YOK-1", "YOK-2", gate_point="activation", satisfaction="status:done")
        blocks = query_frontier_blocks(conn, "activation")
        assert blocks == {}

    def test_gate_point_filter_in_batch(self):
        conn = _create_test_db()
        _insert_item(conn, 1)
        _insert_item(conn, 2, status="implementing")
        _insert_dep(conn, "YOK-1", "YOK-2", gate_point="integration", satisfaction="fact:merged")
        # Activation gate should not see integration deps
        blocks = query_frontier_blocks(conn, "activation")
        assert blocks == {}
        # Integration gate should see them
        blocks = query_frontier_blocks(conn, "integration")
        assert "YOK-1" in blocks

    def test_status_implemented_satisfaction(self):
        """status:implemented satisfied by implemented, release, and done."""
        conn = _create_test_db()
        _insert_item(conn, 1)
        _insert_item(conn, 2, status="implemented")
        _insert_dep(conn, "YOK-1", "YOK-2", gate_point="activation", satisfaction="status:implemented")
        blocks = query_frontier_blocks(conn, "activation")
        assert blocks == {}

    def test_fact_merged_fallback(self):
        """fact:merged without explicit merge check falls back to status heuristic."""
        conn = _create_test_db()
        _insert_item(conn, 1)
        _insert_item(conn, 2, status="release")  # release implies merge
        _insert_dep(conn, "YOK-1", "YOK-2", gate_point="integration", satisfaction="fact:merged")
        blocks = query_frontier_blocks(conn, "integration")
        assert blocks == {}  # release status satisfies fact:merged via fallback

    def test_fact_merged_uses_merged_at(self):
        conn = _create_test_db()
        _insert_item(conn, 1)
        _insert_item(conn, 2, status="implementing")
        conn.execute(
            "UPDATE items SET merged_at = '2026-01-02T00:00:00Z' WHERE id = 2"
        )
        _insert_dep(conn, "YOK-1", "YOK-2", gate_point="integration", satisfaction="fact:merged")
        blocks = query_frontier_blocks(conn, "integration")
        assert blocks == {}
