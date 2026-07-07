"""Tests for yoke_core.domain.lifecycle — invariants, validation,
terminal checks, task-terminal-success, progression helpers, SQL fragments,
and enum completeness."""

from __future__ import annotations

import os
import sys

import pytest

# Ensure the repo root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from yoke_core.domain.lifecycle import (
    ALL_ITEM_STATUSES,
    ALL_TASK_STATUSES,
    BOARD_COLUMN_ORDER,
    EPIC_PROGRESSION,
    EXCEPTIONAL,
    LIFECYCLE_FAMILY,
    LIFECYCLE_SCOPE,
    TERMINAL,
    TERMINAL_FAILURE,
    TERMINAL_SUCCESS,
    ItemStatus,
    TaskStatus,
    is_exceptional,
    is_forward_transition,
    is_task_terminal_success,
    is_terminal,
    is_terminal_failure,
    is_terminal_success,
    is_valid_item_status,
    is_valid_task_status,
    progression_index,
    sql_task_terminal_success_list,
    sql_terminal_failure_list,
    sql_terminal_list,
    sql_terminal_success_list,
    TASK_TERMINAL_SUCCESS,
)


class TestLifecycleInvariants:
    """Exercise canonical invariants on the Python lifecycle source of truth."""

    def test_all_item_statuses_match_enum_order(self):
        """ALL_ITEM_STATUSES must match the ItemStatus enum definition order."""
        assert ALL_ITEM_STATUSES == tuple(s.value for s in ItemStatus)

    def test_all_task_statuses_match_enum_order(self):
        """ALL_TASK_STATUSES must match the TaskStatus enum definition order."""
        assert ALL_TASK_STATUSES == tuple(s.value for s in TaskStatus)

    def test_epic_progression_is_subset_of_item_statuses(self):
        """Every EPIC_PROGRESSION entry must be a valid item status."""
        for status in EPIC_PROGRESSION:
            assert status in ALL_ITEM_STATUSES

    def test_board_column_order_is_non_empty(self):
        assert len(BOARD_COLUMN_ORDER) > 0

    def test_terminal_success_is_subset_of_terminal(self):
        assert TERMINAL_SUCCESS.issubset(TERMINAL)

    def test_terminal_failure_is_subset_of_terminal(self):
        assert TERMINAL_FAILURE.issubset(TERMINAL)

    def test_terminal_disjoint_success_and_failure(self):
        """An item status cannot be both terminal-success and terminal-failure."""
        assert TERMINAL_SUCCESS.isdisjoint(TERMINAL_FAILURE)

    def test_exceptional_disjoint_from_progression(self):
        """Exceptional statuses are not part of the forward progression."""
        assert EXCEPTIONAL.isdisjoint(set(EPIC_PROGRESSION))

    def test_lifecycle_family_present(self):
        assert LIFECYCLE_FAMILY

    def test_lifecycle_scope_present(self):
        assert LIFECYCLE_SCOPE


class TestItemStatusValidation:
    """Test is_valid_item_status against all known statuses."""

    @pytest.mark.parametrize("status", list(ALL_ITEM_STATUSES))
    def test_valid_statuses_accepted(self, status: str):
        assert is_valid_item_status(status) is True

    @pytest.mark.parametrize("status", ["merged", "qa", "validation", "in_release", "unknown", ""])
    def test_invalid_statuses_rejected(self, status: str):
        assert is_valid_item_status(status) is False


class TestTaskStatusValidation:
    """Test is_valid_task_status against all known statuses."""

    @pytest.mark.parametrize("status", list(ALL_TASK_STATUSES))
    def test_valid_statuses_accepted(self, status: str):
        assert is_valid_task_status(status) is True

    @pytest.mark.parametrize("status", [
        "idea", "defined", "review", "designed", "cancelled", "unknown",
        "active", "validate", "passed",  # legacy task statuses rejected
    ])
    def test_invalid_task_statuses_rejected(self, status: str):
        """Epic tasks have a smaller set of valid statuses — no release, etc.
        active, validate, passed are no longer valid task statuses."""
        assert is_valid_task_status(status) is False


class TestTerminalChecks:
    """Test terminal-state classification functions."""

    @pytest.mark.parametrize("status,expected", [
        ("done", True),
        ("stopped", True), ("failed", True),
        ("implementing", False), ("idea", False), ("blocked", False),
    ])
    def test_is_terminal(self, status: str, expected: bool):
        assert is_terminal(status) == expected

    @pytest.mark.parametrize("status,expected", [
        ("done", True),
        ("stopped", False), ("failed", False), ("implementing", False),
    ])
    def test_is_terminal_success(self, status: str, expected: bool):
        assert is_terminal_success(status) == expected

    @pytest.mark.parametrize("status,expected", [
        ("stopped", True), ("failed", True),
        ("done", False), ("implemented", False), ("implementing", False),
    ])
    def test_is_terminal_failure(self, status: str, expected: bool):
        assert is_terminal_failure(status) == expected

    @pytest.mark.parametrize("status,expected", [
        ("blocked", True), ("stopped", True), ("failed", True), ("cancelled", True),
        ("implementing", False), ("done", False), ("idea", False),
    ])
    def test_is_exceptional(self, status: str, expected: bool):
        assert is_exceptional(status) == expected

    def test_is_terminal_covers_every_item_status(self):
        """Every status in ALL_ITEM_STATUSES has a deterministic terminal verdict."""
        for status in ALL_ITEM_STATUSES:
            assert is_terminal(status) == (status in TERMINAL)

    def test_is_terminal_success_covers_every_item_status(self):
        for status in ALL_ITEM_STATUSES:
            assert is_terminal_success(status) == (status in TERMINAL_SUCCESS)

    def test_is_terminal_failure_covers_every_item_status(self):
        for status in ALL_ITEM_STATUSES:
            assert is_terminal_failure(status) == (status in TERMINAL_FAILURE)


class TestTaskTerminalSuccess:
    """Test task-specific terminal success (done|reviewed-implementation)."""

    @pytest.mark.parametrize("status,expected", [
        ("done", True), ("reviewed-implementation", True),
        ("polishing-implementation", True), ("implemented", True),
        ("release", True),
        ("passed", False), ("active", False), ("validate", False),
        ("implementing", False), ("reviewing-implementation", False),
        ("stopped", False), ("failed", False), ("blocked", False),
    ])
    def test_is_task_terminal_success(self, status: str, expected: bool):
        assert is_task_terminal_success(status) == expected

    def test_task_terminal_success_frozenset(self):
        assert TASK_TERMINAL_SUCCESS == frozenset({
            "done", "reviewed-implementation", "polishing-implementation", "implemented",
            "release",
        })

    def test_terminal_success_unchanged(self):
        """AC-9: Item-level TERMINAL_SUCCESS is now just done."""
        assert TERMINAL_SUCCESS == frozenset({"done"})

    def test_sql_task_terminal_success_list(self):
        result = sql_task_terminal_success_list()
        for s in TASK_TERMINAL_SUCCESS:
            assert f"'{s}'" in result

    def test_is_task_terminal_success_covers_every_task_status(self):
        """Every status in ALL_TASK_STATUSES has a deterministic task-terminal verdict."""
        for status in ALL_TASK_STATUSES:
            assert is_task_terminal_success(status) == (status in TASK_TERMINAL_SUCCESS)

    def test_sql_task_terminal_success_list_well_formed(self):
        """The generated SQL list quotes each task-terminal-success status."""
        result = sql_task_terminal_success_list()
        for s in TASK_TERMINAL_SUCCESS:
            assert f"'{s}'" in result


class TestProgressionHelpers:
    """Test epic-progression ordering and forward-transition checks."""

    def test_progression_index_values(self):
        """Each status in EPIC_PROGRESSION has a unique index."""
        for i, status in enumerate(EPIC_PROGRESSION):
            assert progression_index(status) == i

    def test_progression_index_exceptional_returns_none(self):
        """Exceptional statuses are not in the progression."""
        assert progression_index("blocked") is None
        assert progression_index("cancelled") is None
        assert progression_index("stopped") is None
        assert progression_index("failed") is None

    def test_progression_index_unknown_returns_none(self):
        assert progression_index("nonexistent") is None

    def test_forward_transition_normal(self):
        assert is_forward_transition("idea", "planning") is True
        assert is_forward_transition("planning", "planned") is True
        assert is_forward_transition("implementing", "done") is True

    def test_backward_transition_rejected(self):
        assert is_forward_transition("done", "idea") is False
        assert is_forward_transition("planned", "planning") is False

    def test_same_status_not_forward(self):
        assert is_forward_transition("planned", "planned") is False

    def test_exceptional_not_forward(self):
        """Exceptional statuses cannot be forward transitions."""
        assert is_forward_transition("planning", "blocked") is False
        assert is_forward_transition("blocked", "planning") is False

    def test_progression_index_with_item_type_issue(self):
        """progression_index with item_type='issue' uses issue progression."""
        assert progression_index("implementing", item_type="issue") == 3
        # planning is not in issue progression
        assert progression_index("planning", item_type="issue") is None

    def test_forward_transition_with_item_type_issue(self):
        """is_forward_transition with item_type='issue' uses issue progression."""
        assert is_forward_transition("idea", "refining-idea", item_type="issue") is True
        # planning is not in issue progression
        assert is_forward_transition("idea", "planning", item_type="issue") is False


class TestSqlFragments:
    """Test SQL fragment generators.

    The shell-comparison layer was retired — these tests now
    assert that every generator emits well-formed, complete quoted lists
    rooted on the canonical Python sets.
    """

    def test_sql_terminal_success_list(self):
        result = sql_terminal_success_list()
        for s in TERMINAL_SUCCESS:
            assert f"'{s}'" in result

    def test_sql_terminal_failure_list(self):
        result = sql_terminal_failure_list()
        for s in TERMINAL_FAILURE:
            assert f"'{s}'" in result

    def test_sql_terminal_list(self):
        result = sql_terminal_list()
        for s in TERMINAL:
            assert f"'{s}'" in result


class TestEnumCompleteness:
    """Ensure enums cover all statuses and no extras slip in."""

    def test_item_status_enum_count(self):
        assert len(ItemStatus) == len(ALL_ITEM_STATUSES)

    def test_task_status_enum_count(self):
        assert len(TaskStatus) == len(ALL_TASK_STATUSES)

    def test_item_status_values_are_all_item_statuses(self):
        """Enum values in order must equal ALL_ITEM_STATUSES."""
        assert tuple(s.value for s in ItemStatus) == ALL_ITEM_STATUSES

    def test_task_status_values_are_all_task_statuses(self):
        assert tuple(s.value for s in TaskStatus) == ALL_TASK_STATUSES

    def test_board_columns_are_valid_statuses_or_buckets(self):
        """Every board column must be a valid item status or a known display bucket.

        ``refined`` and ``reviewing`` are display buckets.
        """
        display_buckets = {"refined", "reviewing"}
        for col in BOARD_COLUMN_ORDER:
            assert is_valid_item_status(col) or col in display_buckets, (
                f"Board column '{col}' is neither a valid item status nor a display bucket"
            )

    def test_progression_statuses_are_valid(self):
        """Every status in EPIC_PROGRESSION must be a valid item status."""
        for status in EPIC_PROGRESSION:
            assert is_valid_item_status(status), f"Progression status '{status}' is not valid"

    def test_terminal_statuses_are_valid(self):
        for status in TERMINAL:
            assert is_valid_item_status(status)

    def test_exceptional_statuses_are_valid(self):
        for status in EXCEPTIONAL:
            assert is_valid_item_status(status)
