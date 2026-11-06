"""Status-to-bucket mapping tests for yoke_core.domain.board."""

from __future__ import annotations
from yoke_core.domain.workflow_runtime import builtin_workflow_runtime

from yoke_core.domain.board import (
    FROZEN_BUCKET,
    UNKNOWN_BUCKET,
    status_to_board_bucket,
)
from yoke_core.domain.builtin_workflow_definitions import (
    builtin_workflow_definition,
)


def _definition(workflow_id: str):
    return builtin_workflow_definition(workflow_id)["definition"]


class TestStatusToBoardBucket:
    """Test status-to-bucket mapping, mirroring rebuild-board.sh."""

    # --- Direct mappings (no frozen, no active-run) ---

    def test_done_maps_to_done(self):
        assert (
            status_to_board_bucket("done", workflow_definition=_definition("issue"))
            == "done"
        )

    def test_cancelled_maps_to_done(self):
        assert (
            status_to_board_bucket(
                "cancelled", workflow_definition=_definition("issue")
            )
            == "done"
        )

    def test_stopped_maps_to_blocked(self):
        assert (
            status_to_board_bucket("stopped", workflow_definition=_definition("issue"))
            == "blocked"
        )

    def test_failed_maps_to_blocked(self):
        assert (
            status_to_board_bucket("failed", workflow_definition=_definition("issue"))
            == "blocked"
        )

    def test_release_maps_to_release(self):
        assert (
            status_to_board_bucket("release", workflow_definition=_definition("issue"))
            == "release"
        )

    def test_planned_maps_to_refined(self):
        assert (
            status_to_board_bucket("planned", workflow_definition=_definition("epic"))
            == "refined"
        )

    def test_idea_maps_to_idea(self):
        assert (
            status_to_board_bucket("idea", workflow_definition=_definition("issue"))
            == "idea"
        )

    def test_unknown_status_maps_to_unknown(self):
        assert (
            status_to_board_bucket("bogus", workflow_definition=_definition("issue"))
            == UNKNOWN_BUCKET
        )

    # --- Frozen override ---

    def test_frozen_active_goes_to_frozen_bucket(self):
        assert (
            status_to_board_bucket(
                "implementing", frozen_value=1, workflow_definition=_definition("issue")
            )
            == FROZEN_BUCKET
        )

    def test_frozen_idea_goes_to_frozen_bucket(self):
        assert (
            status_to_board_bucket(
                "idea", frozen_value=1, workflow_definition=_definition("issue")
            )
            == FROZEN_BUCKET
        )

    def test_frozen_done_still_goes_to_done(self):
        """Done items bypass the frozen check."""
        assert (
            status_to_board_bucket(
                "done",
                frozen_value=1,
                workflow_definition=builtin_workflow_runtime("issue").definition,
            )
            == "done"
        )

    def test_frozen_cancelled_still_goes_to_done(self):
        """Cancelled items bypass the frozen check."""
        assert (
            status_to_board_bucket(
                "cancelled", frozen_value=1, workflow_definition=_definition("issue")
            )
            == "done"
        )

    def test_null_frozen_is_not_frozen(self):
        assert (
            status_to_board_bucket(
                "implementing",
                frozen_value=None,
                workflow_definition=_definition("issue"),
            )
            == "implementing"
        )

    def test_zero_frozen_is_not_frozen(self):
        assert (
            status_to_board_bucket(
                "implementing", frozen_value=0, workflow_definition=_definition("issue")
            )
            == "implementing"
        )

    # --- FR-7 active-run upgrade ---

    def test_implemented_with_active_run_maps_to_release(self):
        """FR-7: implemented items with an active deployment run become release."""
        assert (
            status_to_board_bucket(
                "implemented",
                has_active_run=True,
                workflow_definition=_definition("issue"),
            )
            == "release"
        )

    def test_implemented_without_active_run_maps_to_implemented(self):
        assert (
            status_to_board_bucket(
                "implemented",
                has_active_run=False,
                workflow_definition=_definition("issue"),
            )
            == "implemented"
        )

    def test_active_run_does_not_affect_non_implemented(self):
        """Active-run upgrade only applies to implemented status."""
        assert (
            status_to_board_bucket(
                "implementing",
                has_active_run=True,
                workflow_definition=_definition("issue"),
            )
            == "implementing"
        )
        assert (
            status_to_board_bucket(
                "done", has_active_run=True, workflow_definition=_definition("issue")
            )
            == "done"
        )
        assert (
            status_to_board_bucket(
                "planned", has_active_run=True, workflow_definition=_definition("epic")
            )
            == "refined"
        )

    def test_frozen_implemented_with_active_run_goes_to_frozen(self):
        """Frozen check takes priority over active-run upgrade."""
        assert (
            status_to_board_bucket(
                "implemented",
                frozen_value=1,
                has_active_run=True,
                workflow_definition=_definition("issue"),
            )
            == FROZEN_BUCKET
        )

    # --- Issue workflow direct mappings ---

    def test_refining_idea_maps_to_planning(self):
        assert (
            status_to_board_bucket(
                "refining-idea", workflow_definition=_definition("issue")
            )
            == "planning"
        )

    def test_refined_idea_maps_to_refined(self):
        assert (
            status_to_board_bucket(
                "refined-idea", workflow_definition=_definition("issue")
            )
            == "refined"
        )

    def test_implementing_maps_to_implementing(self):
        assert (
            status_to_board_bucket(
                "implementing", workflow_definition=_definition("issue")
            )
            == "implementing"
        )

    def test_reviewing_implementation_maps_to_reviewing(self):
        assert (
            status_to_board_bucket(
                "reviewing-implementation", workflow_definition=_definition("issue")
            )
            == "reviewing"
        )

    def test_reviewed_implementation_maps_to_reviewing(self):
        assert (
            status_to_board_bucket(
                "reviewed-implementation", workflow_definition=_definition("issue")
            )
            == "reviewing"
        )

    def test_polishing_implementation_maps_to_reviewing(self):
        assert (
            status_to_board_bucket(
                "polishing-implementation", workflow_definition=_definition("issue")
            )
            == "reviewing"
        )

    def test_implemented_maps_to_implemented(self):
        assert (
            status_to_board_bucket(
                "implemented", workflow_definition=_definition("issue")
            )
            == "implemented"
        )

    # --- Epic workflow direct mappings ---

    def test_planning_maps_to_planning(self):
        """Status_to_board_bucket('planning') returns 'planning'."""
        assert (
            status_to_board_bucket("planning", workflow_definition=_definition("epic"))
            == "planning"
        )

    def test_refining_plan_maps_to_planning(self):
        """Status_to_board_bucket('refining-plan') returns 'planning'."""
        assert (
            status_to_board_bucket(
                "refining-plan", workflow_definition=_definition("epic")
            )
            == "planning"
        )

    # --- Pinned-definition projection ---

    def test_epic_refined_idea_uses_declared_bucket(self):
        """Epic stage metadata declares its refined bucket."""
        assert (
            status_to_board_bucket(
                "refined-idea",
                workflow_definition=_definition("epic"),
            )
            == "refined"
        )

    def test_issue_refined_idea_maps_to_refined(self):
        """Issue + refined-idea -> refined."""
        assert (
            status_to_board_bucket(
                "refined-idea",
                workflow_definition=_definition("issue"),
            )
            == "refined"
        )

    def test_epic_reviewing_implementation_uses_declared_bucket(self):
        """Epic stage metadata declares its review bucket."""
        assert (
            status_to_board_bucket(
                "reviewing-implementation",
                workflow_definition=_definition("epic"),
            )
            == "reviewing"
        )

    def test_issue_reviewing_implementation_maps_to_reviewing(self):
        """Issue + reviewing-implementation -> reviewing (default)."""
        assert (
            status_to_board_bucket(
                "reviewing-implementation",
                workflow_definition=_definition("issue"),
            )
            == "reviewing"
        )

    def test_identity_does_not_override_a_pinned_definition(self):
        assert (
            status_to_board_bucket(
                "refined-idea",
                workflow_id="epic",
                workflow_definition=_definition("issue"),
            )
            == "refined"
        )
