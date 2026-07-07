"""AC-1, AC-2, AC-3, AC-8: Importability and per-status classification.

Covers TestImportability, TestClassifyNextAction, and TestPerStatusClassification
— all DB-free tests that exercise frontier.classify_next_action and the
package-level imports.
"""

from __future__ import annotations

import os
import sys

import pytest

# Ensure the repo root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from yoke_core.domain.frontier import (
    AdapterCategory,
    classify_next_action,
)
from yoke_core.domain.lifecycle import ALL_ITEM_STATUSES


# ---------------------------------------------------------------------------
# Importability
# ---------------------------------------------------------------------------


class TestImportability:
    """AC-1: frontier.py importable from yoke_core.domain.frontier."""

    def test_direct_import(self):
        from yoke_core.domain.frontier import compute_frontier, FrontierResult
        assert callable(compute_frontier)
        assert FrontierResult is not None

    def test_package_reexport(self):
        from yoke_core.domain import (
            AdapterCategory, FrontierItem, FrontierResult,
            classify_next_action, compute_frontier, rank_frontier,
        )
        assert callable(compute_frontier)
        assert callable(classify_next_action)
        assert callable(rank_frontier)


# ---------------------------------------------------------------------------
# classify_next_action maps every canonical status
# ---------------------------------------------------------------------------


class TestClassifyNextAction:
    """AC-3 + AC-8: classify_next_action maps every canonical status."""

    def test_all_canonical_statuses_mapped(self):
        """Every status in ALL_ITEM_STATUSES must map to an adapter category."""
        for status in ALL_ITEM_STATUSES:
            cat = classify_next_action(status)
            assert isinstance(cat, AdapterCategory), f"{status} -> {cat}"

    def test_shepherd_statuses_epic_default(self):
        """Default item_type is 'epic'; planning statuses map to shepherd/refine lanes."""
        for status in ("refined-idea", "planning"):
            assert classify_next_action(status) == AdapterCategory.SHEPHERD

    def test_epic_idea_maps_to_refine(self):
        """FR-4: epic idea -> REFINE (was SHEPHERD)."""
        assert classify_next_action("idea") == AdapterCategory.REFINE

    def test_epic_planned_maps_to_conduct(self):
        """epic planned -> CONDUCT (was SHEPHERD)."""
        assert classify_next_action("planned") == AdapterCategory.CONDUCT

    def test_conduct_statuses(self):
        for status in ("planned", "implementing", "reviewing-implementation"):
            assert classify_next_action(status) == AdapterCategory.CONDUCT

    def test_usher_statuses(self):
        for status in ("implemented", "release"):
            assert classify_next_action(status) == AdapterCategory.USHER

    def test_terminal_statuses(self):
        assert classify_next_action("done") == AdapterCategory.SKIP
        assert classify_next_action("cancelled") == AdapterCategory.SKIP
        assert classify_next_action("stopped") == AdapterCategory.SKIP

    def test_exceptional_statuses(self):
        assert classify_next_action("blocked") == AdapterCategory.WAIT
        assert classify_next_action("failed") == AdapterCategory.WAIT

    def test_unknown_status_raises(self):
        with pytest.raises(ValueError, match="Unknown status"):
            classify_next_action("nonexistent")


# ---------------------------------------------------------------------------
# Individual classification test for every canonical status
# ---------------------------------------------------------------------------


class TestPerStatusClassification:
    """AC-2: Every canonical status has an individual classification test."""

    def test_idea_epic_maps_to_refine(self):
        """FR-4: epic idea -> REFINE."""
        assert classify_next_action("idea") == AdapterCategory.REFINE

    def test_idea_epic_explicit_maps_to_refine(self):
        assert classify_next_action("idea", item_type="epic") == AdapterCategory.REFINE

    def test_defined_is_rejected(self):
        with pytest.raises(ValueError, match="Unknown status"):
            classify_next_action("defined")

    def test_designed_is_rejected(self):
        with pytest.raises(ValueError, match="Unknown status"):
            classify_next_action("designed")

    def test_planned_epic_maps_to_conduct(self):
        """epic planned -> CONDUCT."""
        assert classify_next_action("planned") == AdapterCategory.CONDUCT

    def test_ready_is_rejected(self):
        with pytest.raises(ValueError, match="Unknown status"):
            classify_next_action("ready")

    def test_active_is_rejected(self):
        with pytest.raises(ValueError, match="Unknown status"):
            classify_next_action("active")

    def test_review_is_rejected(self):
        with pytest.raises(ValueError, match="Unknown status"):
            classify_next_action("review")

    def test_validate_is_rejected(self):
        with pytest.raises(ValueError, match="Unknown status"):
            classify_next_action("validate")

    def test_passed_is_rejected(self):
        with pytest.raises(ValueError, match="Unknown status"):
            classify_next_action("passed")

    def test_release_maps_to_usher(self):
        assert classify_next_action("release") == AdapterCategory.USHER

    def test_done_maps_to_skip(self):
        assert classify_next_action("done") == AdapterCategory.SKIP

    def test_cancelled_maps_to_skip(self):
        assert classify_next_action("cancelled") == AdapterCategory.SKIP

    def test_stopped_maps_to_skip(self):
        assert classify_next_action("stopped") == AdapterCategory.SKIP

    def test_blocked_maps_to_wait(self):
        assert classify_next_action("blocked") == AdapterCategory.WAIT

    def test_failed_maps_to_wait(self):
        assert classify_next_action("failed") == AdapterCategory.WAIT

    # -- Epic-workflow-type statuses --

    def test_planning_epic_maps_to_shepherd(self):
        assert classify_next_action("planning") == AdapterCategory.SHEPHERD
        assert classify_next_action("planning", item_type="epic") == AdapterCategory.SHEPHERD

    def test_refining_plan_epic_maps_to_refine(self):
        """epic refining-plan -> REFINE."""
        assert classify_next_action("refining-plan") == AdapterCategory.REFINE
        assert classify_next_action("refining-plan", item_type="epic") == AdapterCategory.REFINE

    def test_refined_idea_epic_maps_to_shepherd(self):
        """epic refined-idea -> SHEPHERD (differs from issue CONDUCT)."""
        assert classify_next_action("refined-idea", item_type="epic") == AdapterCategory.SHEPHERD

    def test_implementing_epic_maps_to_conduct(self):
        """epic implementing -> CONDUCT."""
        assert classify_next_action("implementing", item_type="epic") == AdapterCategory.CONDUCT

    def test_reviewing_implementation_epic_maps_to_conduct(self):
        assert classify_next_action("reviewing-implementation", item_type="epic") == AdapterCategory.CONDUCT

    def test_reviewed_implementation_epic_maps_to_polish(self):
        assert classify_next_action("reviewed-implementation", item_type="epic") == AdapterCategory.POLISH

    def test_polishing_implementation_epic_maps_to_polish(self):
        assert classify_next_action("polishing-implementation", item_type="epic") == AdapterCategory.POLISH

    def test_implemented_epic_maps_to_usher(self):
        assert classify_next_action("implemented", item_type="epic") == AdapterCategory.USHER

    def test_release_epic_maps_to_usher(self):
        assert classify_next_action("release", item_type="epic") == AdapterCategory.USHER

    # -- Issue-workflow-type statuses --

    def test_issue_idea_maps_to_refine(self):
        assert classify_next_action("idea", item_type="issue") == AdapterCategory.REFINE

    def test_refining_idea_maps_to_refine(self):
        assert classify_next_action("refining-idea") == AdapterCategory.REFINE

    def test_refined_idea_issue_maps_to_conduct(self):
        """Issue refined-idea -> CONDUCT (epic refined-idea -> SHEPHERD)."""
        assert classify_next_action("refined-idea", item_type="issue") == AdapterCategory.CONDUCT

    def test_implementing_maps_to_conduct(self):
        assert classify_next_action("implementing") == AdapterCategory.CONDUCT

    def test_reviewing_implementation_maps_to_conduct(self):
        assert classify_next_action("reviewing-implementation") == AdapterCategory.CONDUCT

    def test_reviewed_implementation_maps_to_polish(self):
        assert classify_next_action("reviewed-implementation") == AdapterCategory.POLISH

    def test_polishing_implementation_maps_to_polish(self):
        assert classify_next_action("polishing-implementation") == AdapterCategory.POLISH

    def test_implemented_maps_to_usher(self):
        assert classify_next_action("implemented") == AdapterCategory.USHER

    def test_all_statuses_exhaustive(self):
        """Verify no canonical status is missing from individual tests above."""
        tested = {
            "idea", "planned", "release",
            "done", "cancelled", "stopped", "blocked", "failed",
            # Epic-workflow-type statuses
            "planning", "plan-drafted", "refining-plan",
            # Issue-workflow-type statuses
            "refining-idea", "refined-idea",
            "implementing", "reviewing-implementation",
            "reviewed-implementation",
            "polishing-implementation", "implemented",
        }
        assert tested == set(ALL_ITEM_STATUSES)
