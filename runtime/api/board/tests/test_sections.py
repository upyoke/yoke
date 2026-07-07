"""Tests for yoke_contracts.board.sections — small unit-level helpers + render.

Companion files split off:

- ``test_sections_classify_items.py`` — section assignment for every
  status (active / pipeline / backlog / done / freezer / unknown)
- ``test_sections_frontier_counts.py`` — frontier_counts + consistency_check

Covers status emoji, priority rank, epic progress, epic task subrows,
task_expanded_count, precompute helpers, and render_section table output.
"""

from __future__ import annotations

from yoke_contracts.board.sections import (
    EpicStats,
    ItemRow,
    epic_progress,
    epic_task_rows,
    precompute_epic_stats,
    precompute_epic_task_counts,
    priority_rank,
    render_section,
    status_emoji,
    task_expanded_count,
)
from runtime.api.board.tests.conftest import (
    insert_item,
    insert_task,
)


# ---------------------------------------------------------------------------
# status_emoji
# ---------------------------------------------------------------------------


class TestStatusEmoji:
    def test_all_known_statuses(self):
        known = [
            "idea", "planned", "done", "cancelled", "blocked",
            "stopped", "release", "failed", "planning", "refining-plan",
            "refining-idea", "refined-idea", "implementing",
            "reviewing-implementation", "reviewed-implementation",
            "polishing-implementation", "implemented",
        ]
        for s in known:
            result = status_emoji(s)
            assert s in result, f"Status '{s}' not in emoji result '{result}'"
            assert result != s, f"Expected emoji prefix for '{s}'"

    def test_unknown_status_passthrough(self):
        """AC-4: Unknown statuses pass through without emoji."""
        assert status_emoji("bogus") == "bogus"

    def test_specific_emojis(self):
        assert status_emoji("implementing") == "\U0001f528 implementing"
        assert status_emoji("done") == "✅ done"
        assert status_emoji("blocked") == "⛔ blocked"

    def test_issue_family_statuses(self):
        """Issue-workflow-type statuses have emoji prefixes."""
        issue_statuses = [
            "refining-idea", "refined-idea", "implementing",
            "reviewing-implementation", "reviewed-implementation",
            "polishing-implementation",
            "implemented",
        ]
        for s in issue_statuses:
            result = status_emoji(s)
            assert s in result, f"Status '{s}' not in emoji result '{result}'"
            assert result != s, f"Expected emoji prefix for '{s}'"

    def test_planning_has_emoji(self):
        """AC-6: status_emoji('planning') returns emoji-prefixed string."""
        result = status_emoji("planning")
        assert "planning" in result
        assert result != "planning"
        # Verify it starts with the ruler emoji
        assert result.startswith("📐")

    def test_plan_drafted_has_emoji(self):
        """status_emoji('plan-drafted') returns emoji-prefixed string."""
        result = status_emoji("plan-drafted")
        assert "plan-drafted" in result
        assert result != "plan-drafted"

    def test_refining_plan_has_emoji(self):
        """AC-7: status_emoji('refining-plan') returns emoji-prefixed string."""
        result = status_emoji("refining-plan")
        assert "refining-plan" in result
        assert result != "refining-plan"
        # Verify it starts with the memo emoji
        assert result.startswith("📝")


# ---------------------------------------------------------------------------
# priority_rank
# ---------------------------------------------------------------------------


class TestPriorityRank:
    def test_all_known_priorities(self):
        assert priority_rank("critical") == 1
        assert priority_rank("high") == 2
        assert priority_rank("medium") == 3
        assert priority_rank("low") == 4

    def test_unknown_priority(self):
        assert priority_rank("unknown") == 5
        assert priority_rank("") == 5


# ---------------------------------------------------------------------------
# epic_progress
# ---------------------------------------------------------------------------


class TestEpicProgress:
    def test_no_tasks(self, test_db):
        assert epic_progress(test_db, 999) == "—"

    def test_none_epic_id(self, test_db):
        assert epic_progress(test_db, None) == "—"

    def test_all_done(self, test_db):
        insert_task(test_db, 10, 1, "Task 1", "done")
        insert_task(test_db, 10, 2, "Task 2", "reviewed-implementation")
        result = epic_progress(test_db, 10)
        assert result == "2/2 (100%)"

    def test_partial_progress(self, test_db):
        insert_task(test_db, 20, 1, "Task 1", "done")
        insert_task(test_db, 20, 2, "Task 2", "implementing")
        insert_task(test_db, 20, 3, "Task 3", "blocked")
        result = epic_progress(test_db, 20)
        assert result == "1/3 (33%)"

    def test_zero_progress(self, test_db):
        insert_task(test_db, 30, 1, "Task 1", "implementing")
        insert_task(test_db, 30, 2, "Task 2", "blocked")
        result = epic_progress(test_db, 30)
        assert result == "0/2 (0%)"

    def test_all_implemented(self, test_db):
        insert_task(test_db, 31, 1, "Task 1", "implemented")
        insert_task(test_db, 31, 2, "Task 2", "implemented")
        result = epic_progress(test_db, 31)
        assert result == "2/2 (100%)"

    def test_all_polishing(self, test_db):
        insert_task(test_db, 32, 1, "Task 1", "polishing-implementation")
        insert_task(test_db, 32, 2, "Task 2", "polishing-implementation")
        result = epic_progress(test_db, 32)
        assert result == "2/2 (100%)"

    def test_all_release(self, test_db):
        insert_task(test_db, 33, 1, "Task 1", "release")
        insert_task(test_db, 33, 2, "Task 2", "release")
        result = epic_progress(test_db, 33)
        assert result == "2/2 (100%)"

    def test_mixed_terminal_success(self, test_db):
        insert_task(test_db, 34, 1, "Task 1", "done")
        insert_task(test_db, 34, 2, "Task 2", "implemented")
        insert_task(test_db, 34, 3, "Task 3", "implementing")
        result = epic_progress(test_db, 34)
        assert result == "2/3 (66%)"


# ---------------------------------------------------------------------------
# epic_task_rows
# ---------------------------------------------------------------------------


class TestEpicTaskRows:
    def test_no_tasks(self, test_db):
        assert epic_task_rows(test_db, 999, "YOK-999") == []

    def test_task_rows_format(self, test_db):
        insert_task(test_db, 40, 1, "First task", "implementing")
        insert_task(test_db, 40, 2, "Second task", "done")
        rows = epic_task_rows(test_db, 40, "YOK-40 ")
        assert len(rows) == 2
        assert "└" in rows[0]
        assert "└" in rows[1]
        assert "001:" in rows[0]
        assert "002:" in rows[1]
        assert "implementing" in rows[0]
        assert "done" in rows[1]

    def test_padding_alignment(self, test_db):
        insert_task(test_db, 50, 1, "A task", "implementing")
        rows_short = epic_task_rows(test_db, 50, "YOK-50")
        rows_long = epic_task_rows(test_db, 50, "YOK-1234")
        assert len(rows_long[0]) > len(rows_short[0])


# ---------------------------------------------------------------------------
# task_expanded_count
# ---------------------------------------------------------------------------


class TestTaskExpandedCount:
    def test_no_epics(self):
        items = [
            ItemRow(3, "YOK-1", "T1", "issue", "medium", "implementing", "—", None, "", "yoke", ""),
            ItemRow(3, "YOK-2", "T2", "issue", "medium", "implementing", "—", None, "", "yoke", ""),
        ]
        assert task_expanded_count(items, {}) == 2

    def test_epic_with_tasks(self):
        items = [
            ItemRow(3, "YOK-1", "T1", "issue", "medium", "implementing", "—", None, "", "yoke", ""),
            ItemRow(3, "YOK-2", "Epic", "epic", "medium", "implementing", "2/5 (40%)", 2, "", "yoke", ""),
        ]
        epic_counts = {2: 5}
        assert task_expanded_count(items, epic_counts) == 6

    def test_epic_without_tasks(self):
        items = [
            ItemRow(3, "YOK-1", "Epic", "epic", "medium", "implementing", "—", 1, "", "yoke", ""),
        ]
        assert task_expanded_count(items, {}) == 1

    def test_epic_no_epic_id(self):
        items = [
            ItemRow(3, "YOK-1", "Epic", "epic", "medium", "implementing", "—", None, "", "yoke", ""),
        ]
        assert task_expanded_count(items, {5: 10}) == 1


# ---------------------------------------------------------------------------
# precompute_epic_stats / precompute_epic_task_counts
# ---------------------------------------------------------------------------


class TestPrecomputeEpicStats:
    def test_empty(self, test_db):
        result = precompute_epic_stats(test_db, "yoke")
        assert result == {}

    def test_with_tasks(self, test_db):
        insert_item(test_db, 10, type="epic")
        insert_task(test_db, 10, 1, "T1", "done")
        insert_task(test_db, 10, 2, "T2", "implementing")
        insert_task(test_db, 10, 3, "T3", "blocked")
        result = precompute_epic_stats(test_db, "yoke")
        assert 10 in result
        assert result[10].task_count == 3
        assert result[10].progress == "1/3 (33%)"

    def test_all_done(self, test_db):
        insert_item(test_db, 20, type="epic")
        insert_task(test_db, 20, 1, "T1", "done")
        insert_task(test_db, 20, 2, "T2", "reviewed-implementation")
        result = precompute_epic_stats(test_db, "yoke")
        assert result[20].task_count == 2
        assert result[20].progress == "2/2 (100%)"

    def test_multiple_epics_batched(self, test_db):
        insert_item(test_db, 30, type="epic")
        insert_item(test_db, 31, type="epic")
        insert_task(test_db, 30, 1, "T1", "done")
        insert_task(test_db, 31, 1, "T1", "implementing")
        insert_task(test_db, 31, 2, "T2", "implementing")
        result = precompute_epic_stats(test_db, "yoke")
        assert result[30] == EpicStats(task_count=1, progress="1/1 (100%)")
        assert result[31] == EpicStats(task_count=2, progress="0/2 (0%)")


class TestPrecomputeEpicTaskCounts:
    """Legacy wrapper tests — delegates to precompute_epic_stats."""

    def test_empty(self, test_db):
        result = precompute_epic_task_counts(test_db, "yoke")
        assert result == {}

    def test_with_tasks(self, test_db):
        insert_item(test_db, 10, type="epic")
        insert_task(test_db, 10, 1, "T1", "done")
        insert_task(test_db, 10, 2, "T2", "implementing")
        insert_task(test_db, 10, 3, "T3", "blocked")
        result = precompute_epic_task_counts(test_db, "yoke")
        assert result == {10: 3}


# ---------------------------------------------------------------------------
# render_section
# ---------------------------------------------------------------------------


class TestRenderSection:
    def test_empty_section(self, test_db):
        result = render_section("Active", [], {}, test_db, "\U0001f535", 7)
        assert result == ""

    def test_section_format(self, test_db):
        items = [
            ItemRow(1, "YOK-1", "Critical item", "issue", "critical", "implementing",
                    "—", None, "", "yoke", "2024-01-01"),
        ]
        result = render_section("Active", items, {}, test_db, "\U0001f535", 7)
        lines = result.split("\n")
        assert "### \U0001f535 Active (1)" == lines[0]
        assert lines[1] == ""
        assert "| ID" in lines[2]
        assert "Status" in lines[2]
        assert "Project" in lines[2]
        assert lines[3].startswith("|---")
        assert "YOK-1" in lines[4]
        assert "implementing" in lines[4]
        assert "critical" in lines[4]

    def test_section_with_epic_subrows(self, test_db):
        insert_item(test_db, 200, type="epic", status="implementing")
        insert_task(test_db, 200, 1, "Sub task 1", "done")
        insert_task(test_db, 200, 2, "Sub task 2", "implementing")

        items = [
            ItemRow(3, "YOK-200", "My Epic", "epic", "medium", "implementing",
                    "1/2 (50%)", 200, "", "yoke", "2024-01-01"),
        ]
        epic_counts = {200: 2}
        result = render_section("Active", items, epic_counts, test_db, "\U0001f535", 7)
        lines = result.split("\n")
        corner_lines = [line for line in lines if "└" in line]
        assert len(corner_lines) == 2
        assert "001:" in corner_lines[0]
        assert "002:" in corner_lines[1]

    def test_task_expanded_count_in_heading(self, test_db):
        insert_item(test_db, 300, type="epic", status="implementing")
        insert_task(test_db, 300, 1, "T1", "done")
        insert_task(test_db, 300, 2, "T2", "implementing")
        insert_task(test_db, 300, 3, "T3", "blocked")

        items = [
            ItemRow(3, "YOK-300", "Big Epic", "epic", "medium", "implementing",
                    "1/3 (33%)", 300, "", "yoke", ""),
        ]
        epic_counts = {300: 3}
        result = render_section("Active", items, epic_counts, test_db, "\U0001f535", 7)
        assert "(3)" in result.split("\n")[0]
