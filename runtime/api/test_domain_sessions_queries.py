"""Query-related tests for yoke_core.domain — frozen, ItemFilter, classify."""

from __future__ import annotations

from yoke_core.domain.queries import (
    ItemFilter,
    active_queue_filter,
    build_where_clause,
    classify_item_state,
    is_frozen,
    pending_work_filter,
    sql_frozen_filter,
)


class TestFrozenSemantics:
    """Test frozen value interpretation matching shell behavior.

    Shell: (frozen IS NULL OR frozen = 0) -> not frozen, frozen = 1 -> frozen.
    """

    def test_none_is_not_frozen(self):
        assert is_frozen(None) is False

    def test_zero_is_not_frozen(self):
        assert is_frozen(0) is False

    def test_one_is_frozen(self):
        assert is_frozen(1) is True

    def test_false_is_not_frozen(self):
        assert is_frozen(False) is False

    def test_true_is_frozen(self):
        assert is_frozen(True) is True

    def test_string_one_is_frozen(self):
        """Edge case: string '1' from some DB drivers."""
        assert is_frozen("1") is True

    def test_string_zero_is_not_frozen(self):
        assert is_frozen("0") is False

    def test_string_true_is_frozen(self):
        assert is_frozen("true") is True

    def test_string_false_is_not_frozen(self):
        assert is_frozen("false") is False

    def test_sql_frozen_filter_frozen(self):
        result = sql_frozen_filter(True)
        assert result == "frozen = 1"

    def test_sql_frozen_filter_not_frozen(self):
        result = sql_frozen_filter(False)
        assert result == "(frozen IS NULL OR frozen = 0)"

    def test_sql_frozen_filter_custom_column(self):
        result = sql_frozen_filter(False, col="i.frozen")
        assert result == "(i.frozen IS NULL OR i.frozen = 0)"

    def test_sql_frozen_filter_frozen_custom_column(self):
        result = sql_frozen_filter(True, col="i.frozen")
        assert result == "i.frozen = 1"


class TestItemFilter:
    """Test declarative item filter and WHERE clause generation."""

    def test_empty_filter_produces_no_where(self):
        filt = ItemFilter()
        clause, params = build_where_clause(filt)
        assert clause == ""
        assert params == []

    def test_single_status_filter(self):
        filt = ItemFilter(status="implementing")
        clause, params = build_where_clause(filt)
        assert "status = %s" in clause
        assert params == ["implementing"]

    def test_multi_status_comma_list_matches_any(self):
        """Comma-separated status matches any listed value — the old
        exact match made multi-status recipes silently match zero rows."""
        filt = ItemFilter(status="idea, refining-idea,refined-idea")
        clause, params = build_where_clause(filt)
        assert "status IN (%s, %s, %s)" in clause
        assert params[:3] == ["idea", "refining-idea", "refined-idea"]

    def test_single_project_filter(self):
        filt = ItemFilter(project="yoke")
        clause, params = build_where_clause(filt)
        assert "project_id = (" in clause
        assert "WHERE slug = %s OR CAST(id AS TEXT) = %s" in clause
        assert params == ["yoke", "yoke"]

    def test_frozen_filter_true(self):
        filt = ItemFilter(frozen=True)
        clause, params = build_where_clause(filt)
        assert "frozen = 1" in clause
        assert params == []  # frozen filter is literal, no params

    def test_frozen_filter_false(self):
        filt = ItemFilter(frozen=False)
        clause, params = build_where_clause(filt)
        assert "(frozen IS NULL OR frozen = 0)" in clause
        assert params == []

    def test_multiple_filters_combined(self):
        filt = ItemFilter(status="implementing", project="yoke")
        clause, params = build_where_clause(filt)
        assert clause.startswith("WHERE ")
        assert "status = %s" in clause
        assert "project_id = (" in clause
        assert "implementing" in params
        assert "yoke" in params

    def test_exclude_statuses(self):
        filt = ItemFilter(exclude_statuses=["done", "cancelled"])
        clause, params = build_where_clause(filt)
        assert "status NOT IN" in clause
        assert "done" in params
        assert "cancelled" in params

    def test_exclude_cancelled(self):
        filt = ItemFilter(exclude_cancelled=True)
        clause, params = build_where_clause(filt)
        assert "status <> %s" in clause
        assert "cancelled" in params

    def test_exclude_done(self):
        filt = ItemFilter(exclude_done=True)
        clause, params = build_where_clause(filt)
        assert "status <> %s" in clause
        assert "done" in params

    def test_exclude_frozen(self):
        filt = ItemFilter(exclude_frozen=True)
        clause, params = build_where_clause(filt)
        assert "(frozen IS NULL OR frozen = 0)" in clause

    def test_table_prefix(self):
        filt = ItemFilter(status="implementing", project="externalwebapp")
        clause, params = build_where_clause(filt, table_prefix="i.")
        assert "i.status = %s" in clause
        assert "i.project_id = (" in clause

    def test_all_inclusion_filters(self):
        filt = ItemFilter(
            status="implementing",
            priority="high",
            item_type="epic",
            frozen=False,
            project="yoke",
        )
        clause, params = build_where_clause(filt)
        assert "status = %s" in clause
        assert "priority = %s" in clause
        assert "type = %s" in clause
        assert "(frozen IS NULL OR frozen = 0)" in clause
        assert "project_id = (" in clause
        assert len(params) == 5  # frozen filter is literal, project uses slug/id params


class TestAnalysisFilters:
    """Test pre-built analysis filters."""

    def test_active_queue_filter_defaults(self):
        filt = active_queue_filter()
        assert filt.exclude_done is True
        assert filt.exclude_cancelled is True
        assert filt.exclude_frozen is True
        assert filt.project is None

    def test_active_queue_filter_scoped(self):
        filt = active_queue_filter(project="yoke")
        assert filt.project == "yoke"
        assert filt.exclude_done is True
        assert filt.exclude_cancelled is True
        assert filt.exclude_frozen is True

    def test_active_queue_filter_produces_valid_where(self):
        filt = active_queue_filter(project="yoke")
        clause, params = build_where_clause(filt)
        assert "WHERE" in clause
        assert "status <> %s" in clause  # exclude done
        assert "(frozen IS NULL OR frozen = 0)" in clause
        assert "project_id = (" in clause

    def test_pending_work_filter_excludes_implemented(self):
        filt = pending_work_filter()
        assert filt.exclude_statuses is not None
        assert "implemented" in filt.exclude_statuses
        assert "done" in filt.exclude_statuses
        assert "cancelled" in filt.exclude_statuses
        assert filt.exclude_frozen is True


class TestClassifyItemState:
    """Test high-level item state classification."""

    def test_done_is_done(self):
        assert classify_item_state("done", 0) == "done"

    def test_cancelled_is_cancelled(self):
        assert classify_item_state("cancelled", 0) == "cancelled"

    def test_frozen_implementing_is_frozen(self):
        assert classify_item_state("implementing", 1) == "frozen"

    def test_frozen_idea_is_frozen(self):
        assert classify_item_state("idea", 1) == "frozen"

    def test_frozen_done_is_done(self):
        """Done items are done even if frozen flag is set."""
        assert classify_item_state("done", 1) == "done"

    def test_frozen_cancelled_is_cancelled(self):
        assert classify_item_state("cancelled", 1) == "cancelled"

    def test_stopped_is_terminal_failure(self):
        assert classify_item_state("stopped", 0) == "terminal_failure"

    def test_failed_is_terminal_failure(self):
        assert classify_item_state("failed", 0) == "terminal_failure"

    def test_implementing_is_active_work(self):
        assert classify_item_state("implementing", 0) == "active_work"

    def test_reviewing_implementation_is_active_work(self):
        assert classify_item_state("reviewing-implementation", 0) == "active_work"

    def test_implemented_is_active_work(self):
        assert classify_item_state("implemented", 0) == "active_work"

    def test_release_is_active_work(self):
        assert classify_item_state("release", 0) == "active_work"

    def test_blocked_is_active_work(self):
        assert classify_item_state("blocked", 0) == "active_work"

    def test_idea_is_pipeline(self):
        assert classify_item_state("idea", 0) == "pipeline"

    def test_refined_idea_is_pipeline(self):
        assert classify_item_state("refined-idea", 0) == "pipeline"

    def test_planning_is_pipeline(self):
        assert classify_item_state("planning", 0) == "pipeline"

    def test_planned_is_pipeline(self):
        assert classify_item_state("planned", 0) == "pipeline"

    def test_null_frozen_is_not_frozen(self):
        """None frozen value = not frozen."""
        assert classify_item_state("implementing", None) == "active_work"
