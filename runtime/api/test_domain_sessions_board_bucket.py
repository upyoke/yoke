"""Status-to-bucket mapping tests for yoke_core.domain.board."""

from __future__ import annotations

from yoke_core.domain.board import (
    FROZEN_BUCKET,
    UNKNOWN_BUCKET,
    status_to_board_bucket,
)


class TestStatusToBoardBucket:
    """Test status-to-bucket mapping, mirroring rebuild-board.sh."""

    # --- Direct mappings (no frozen, no active-run) ---

    def test_done_maps_to_done(self):
        assert status_to_board_bucket("done") == "done"

    def test_cancelled_maps_to_done(self):
        assert status_to_board_bucket("cancelled") == "done"

    def test_blocked_maps_to_blocked(self):
        assert status_to_board_bucket("blocked") == "blocked"

    def test_stopped_maps_to_blocked(self):
        assert status_to_board_bucket("stopped") == "blocked"

    def test_failed_maps_to_blocked(self):
        assert status_to_board_bucket("failed") == "blocked"

    def test_legacy_validate_maps_to_unknown(self):
        assert status_to_board_bucket("validate") == UNKNOWN_BUCKET

    def test_legacy_passed_maps_to_unknown(self):
        assert status_to_board_bucket("passed") == UNKNOWN_BUCKET

    def test_release_maps_to_release(self):
        assert status_to_board_bucket("release") == "release"

    def test_legacy_active_maps_to_unknown(self):
        assert status_to_board_bucket("active") == UNKNOWN_BUCKET

    def test_legacy_review_maps_to_unknown(self):
        assert status_to_board_bucket("review") == UNKNOWN_BUCKET

    def test_legacy_ready_maps_to_unknown(self):
        assert status_to_board_bucket("ready") == UNKNOWN_BUCKET

    def test_planned_maps_to_refined(self):
        assert status_to_board_bucket("planned") == "refined"

    def test_legacy_designed_maps_to_unknown(self):
        assert status_to_board_bucket("designed") == UNKNOWN_BUCKET

    def test_legacy_defined_maps_to_unknown(self):
        assert status_to_board_bucket("defined") == UNKNOWN_BUCKET

    def test_idea_maps_to_idea(self):
        assert status_to_board_bucket("idea") == "idea"

    def test_unknown_status_maps_to_unknown(self):
        assert status_to_board_bucket("bogus") == UNKNOWN_BUCKET

    # --- Frozen override ---

    def test_frozen_active_goes_to_frozen_bucket(self):
        assert status_to_board_bucket("implementing", frozen_value=1) == FROZEN_BUCKET

    def test_frozen_idea_goes_to_frozen_bucket(self):
        assert status_to_board_bucket("idea", frozen_value=1) == FROZEN_BUCKET

    def test_frozen_done_still_goes_to_done(self):
        """Done items bypass the frozen check."""
        assert status_to_board_bucket("done", frozen_value=1) == "done"

    def test_frozen_cancelled_still_goes_to_done(self):
        """Cancelled items bypass the frozen check."""
        assert status_to_board_bucket("cancelled", frozen_value=1) == "done"

    def test_null_frozen_is_not_frozen(self):
        assert status_to_board_bucket("implementing", frozen_value=None) == "implementing"

    def test_zero_frozen_is_not_frozen(self):
        assert status_to_board_bucket("implementing", frozen_value=0) == "implementing"

    # --- FR-7 active-run upgrade ---

    def test_implemented_with_active_run_maps_to_release(self):
        """FR-7: implemented items with an active deployment run become release."""
        assert status_to_board_bucket("implemented", has_active_run=True) == "release"

    def test_implemented_without_active_run_maps_to_implemented(self):
        assert status_to_board_bucket("implemented", has_active_run=False) == "implemented"

    def test_active_run_does_not_affect_non_implemented(self):
        """Active-run upgrade only applies to implemented status."""
        assert status_to_board_bucket("implementing", has_active_run=True) == "implementing"
        assert status_to_board_bucket("done", has_active_run=True) == "done"
        assert status_to_board_bucket("planned", has_active_run=True) == "refined"

    def test_frozen_implemented_with_active_run_goes_to_frozen(self):
        """Frozen check takes priority over active-run upgrade."""
        assert status_to_board_bucket(
            "implemented", frozen_value=1, has_active_run=True
        ) == FROZEN_BUCKET

    # --- Issue-workflow-type direct mappings ---

    def test_refining_idea_maps_to_planning(self):
        assert status_to_board_bucket("refining-idea") == "planning"

    def test_refined_idea_maps_to_refined(self):
        assert status_to_board_bucket("refined-idea") == "refined"

    def test_implementing_maps_to_implementing(self):
        assert status_to_board_bucket("implementing") == "implementing"

    def test_reviewing_implementation_maps_to_reviewing(self):
        assert status_to_board_bucket("reviewing-implementation") == "reviewing"

    def test_reviewed_implementation_maps_to_reviewing(self):
        assert status_to_board_bucket("reviewed-implementation") == "reviewing"

    def test_polishing_implementation_maps_to_reviewing(self):
        assert status_to_board_bucket("polishing-implementation") == "reviewing"

    def test_implemented_maps_to_implemented(self):
        assert status_to_board_bucket("implemented") == "implemented"

    # --- Epic-workflow-type direct mappings ---

    def test_planning_maps_to_planning(self):
        """AC-3: status_to_board_bucket('planning') returns 'planning'."""
        assert status_to_board_bucket("planning") == "planning"

    def test_refining_plan_maps_to_planning(self):
        """AC-4: status_to_board_bucket('refining-plan') returns 'planning'."""
        assert status_to_board_bucket("refining-plan") == "planning"

    # --- Type-aware overrides ---

    def test_epic_refined_idea_maps_to_planning(self):
        """AC-1: epic + refined-idea -> planning."""
        assert status_to_board_bucket("refined-idea", item_type="epic") == "planning"

    def test_issue_refined_idea_maps_to_refined(self):
        """AC-2: issue + refined-idea -> refined."""
        assert status_to_board_bucket("refined-idea", item_type="issue") == "refined"

    def test_epic_reviewing_implementation_maps_to_implementing(self):
        """AC-5: epic + reviewing-implementation -> implementing."""
        assert status_to_board_bucket("reviewing-implementation", item_type="epic") == "implementing"

    def test_issue_reviewing_implementation_maps_to_reviewing(self):
        """Issue + reviewing-implementation -> reviewing (default)."""
        assert status_to_board_bucket("reviewing-implementation", item_type="issue") == "reviewing"

    def test_no_item_type_legacy_active_is_unknown(self):
        """AC-8: legacy active status no longer has a compatibility mapping."""
        assert status_to_board_bucket("active") == UNKNOWN_BUCKET

    def test_epic_active_no_override(self):
        """Epic + legacy active has no compatibility override."""
        assert status_to_board_bucket("active", item_type="epic") == UNKNOWN_BUCKET

    def test_issue_implementing_no_override(self):
        """Issue + implementing has no type-aware override, uses standard mapping."""
        assert status_to_board_bucket("implementing", item_type="issue") == "implementing"
