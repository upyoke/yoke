"""Tests for yoke_core.domain.lifecycle — epic-workflow-type validation,
progression, and forward-transition helpers."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from yoke_core.domain.lifecycle import (
    ALL_EPIC_STATUSES,
    ALL_ITEM_STATUSES,
    EPIC_PROGRESSION,
    EXCEPTIONAL,
    EpicStatus,
    ItemStatus,
    epic_progression_index,
    is_epic_forward_transition,
    is_valid_epic_status,
    is_valid_item_status,
    progression_index,
)


class TestEpicLifecycle:
    """Test epic-workflow-type lifecycle constants, validation, and progression."""

    def test_epic_status_enum_count(self):
        """EpicStatus enum has exactly 14 members."""
        assert len(EpicStatus) == 14

    def test_all_epic_statuses_match_enum_order(self):
        """ALL_EPIC_STATUSES must match the EpicStatus enum definition order."""
        assert ALL_EPIC_STATUSES == tuple(s.value for s in EpicStatus)

    def test_epic_progression_is_subset_of_all_epic_statuses(self):
        """Every EPIC_PROGRESSION entry must be a valid epic status."""
        for status in EPIC_PROGRESSION:
            assert status in ALL_EPIC_STATUSES

    def test_epic_progression_statuses_are_valid(self):
        """Every status in EPIC_PROGRESSION must be a valid item status."""
        for status in EPIC_PROGRESSION:
            assert is_valid_item_status(status), (
                f"EPIC_PROGRESSION status '{status}' is not a valid item status"
            )

    def test_epic_progression_statuses_are_valid_epic(self):
        """Every status in EPIC_PROGRESSION must be a valid epic status."""
        for status in EPIC_PROGRESSION:
            assert is_valid_epic_status(status), (
                f"EPIC_PROGRESSION status '{status}' is not a valid epic status"
            )

    def test_is_valid_epic_status_accepts_progression(self):
        """All epic-workflow-type progression statuses are valid."""
        for status in ALL_EPIC_STATUSES:
            assert is_valid_epic_status(status) is True

    def test_is_valid_epic_status_accepts_exceptional(self):
        """Exceptional statuses are valid for epic items."""
        for status in EXCEPTIONAL:
            assert is_valid_epic_status(status) is True

    def test_is_valid_epic_status_rejects_legacy(self):
        """Legacy shared-only statuses are rejected for epic items."""
        legacy = ["defined", "designed", "ready", "active", "review", "validate", "passed"]
        for status in legacy:
            assert is_valid_epic_status(status) is False, (
                f"Legacy status '{status}' should be rejected for epic items"
            )

    def test_is_valid_epic_status_planning_true(self):
        """AC-4: is_valid_epic_status('planning') returns True."""
        assert is_valid_epic_status("planning") is True

    def test_is_valid_epic_status_plan_drafted_true(self):
        """AC-4: is_valid_epic_status('plan-drafted') returns True."""
        assert is_valid_epic_status("plan-drafted") is True

    def test_is_valid_epic_status_defined_false(self):
        """AC-4: is_valid_epic_status('defined') returns False."""
        assert is_valid_epic_status("defined") is False

    def test_epic_progression_index_planning(self):
        """AC-5: epic_progression_index('planning') returns 3."""
        assert epic_progression_index("planning") == 3

    def test_epic_progression_index_blocked_none(self):
        """AC-5: epic_progression_index('blocked') returns None."""
        assert epic_progression_index("blocked") is None

    def test_epic_progression_index_all(self):
        """Each status in EPIC_PROGRESSION has a unique index."""
        for i, status in enumerate(EPIC_PROGRESSION):
            assert epic_progression_index(status) == i

    def test_is_epic_forward_transition_normal(self):
        """AC-6: is_epic_forward_transition('refined-idea', 'planning') returns True."""
        assert is_epic_forward_transition("refined-idea", "planning") is True
        assert is_epic_forward_transition("idea", "done") is True
        assert is_epic_forward_transition("planning", "planned") is True

    def test_is_epic_forward_transition_backward_rejected(self):
        """Backward transitions in epic progression are rejected."""
        assert is_epic_forward_transition("planning", "idea") is False
        assert is_epic_forward_transition("done", "planning") is False

    def test_is_epic_forward_transition_exceptional(self):
        """Exceptional statuses are not forward in epic progression."""
        assert is_epic_forward_transition("planning", "blocked") is False
        assert is_epic_forward_transition("blocked", "planning") is False

    def test_item_status_planning_exists(self):
        """AC-8: ItemStatus.PLANNING exists."""
        assert ItemStatus.PLANNING.value == "planning"

    def test_item_status_plan_drafted_exists(self):
        """AC-8: ItemStatus.PLAN_DRAFTED exists."""
        assert ItemStatus.PLAN_DRAFTED.value == "plan-drafted"

    def test_item_status_refining_plan_exists(self):
        """AC-8: ItemStatus.REFINING_PLAN exists."""
        assert ItemStatus.REFINING_PLAN.value == "refining-plan"

    def test_all_item_statuses_include_epic_tokens(self):
        """AC-9: ALL_ITEM_STATUSES includes epic-only lifecycle tokens."""
        assert "planning" in ALL_ITEM_STATUSES
        assert "plan-drafted" in ALL_ITEM_STATUSES
        assert "refining-plan" in ALL_ITEM_STATUSES

    def test_backward_compat_progression_index_planning(self):
        """AC-7: progression_index('planning') returns the epic index."""
        assert progression_index("planning") == 3
