"""Regression tests for done-transition preconditions.

Latest deploy_run not failed.
Epic refined_idea_to_planning verdict required.
No-run-delivery flow bypass.

Plus short-circuit cases for empty / internal / unregistered flows.
The deployed_to and deploy_stage preconditions live in the sibling
``test_done_transition_preconditions`` module to fit the 350-line cap.
"""

from __future__ import annotations

from yoke_core.engines import done_transition  # noqa: F401 — parent registration
from yoke_core.engines.done_transition_preconditions import (
    check_done_preconditions,
)

from runtime.api.engines._done_transition_test_helpers import (
    _insert_item,
)


from runtime.api.engines.test_done_transition_preconditions_epic_and_runs import (
    _seed_registered_flow,
    _seed_deploy_run,
)


class TestAncillaryRunDoesNotAttestDelivery:
    """A succeeded carrying run on another flow is not this item's delivery."""

    def test_succeeded_other_flow_does_not_skip_deployed_to(self, dt_db):
        db_path, _ = dt_db
        _seed_registered_flow(db_path, flow_id="prod-flow")
        _seed_registered_flow(db_path, flow_id="stage-flow")
        _insert_item(
            db_path,
            771,
            deployment_flow="prod-flow",
            deploy_stage=None,
            deployed_to=None,
        )
        _seed_deploy_run(db_path, 771, "succeeded", flow="stage-flow")

        allowed, reason = check_done_preconditions(771, "prod-flow", False)

        assert allowed is False
        assert "deployed_to is empty" in reason

    def test_failed_selected_flow_blocks_despite_other_flow_success(self, dt_db):
        db_path, _ = dt_db
        _seed_registered_flow(db_path, flow_id="prod-flow")
        _seed_registered_flow(db_path, flow_id="stage-flow")
        _insert_item(
            db_path,
            772,
            deployment_flow="prod-flow",
            deploy_stage="complete",
            deployed_to="prod",
        )
        _seed_deploy_run(db_path, 772, "failed", flow="prod-flow")
        _seed_deploy_run(db_path, 772, "succeeded", flow="stage-flow")

        allowed, reason = check_done_preconditions(772, "prod-flow", False)

        assert allowed is False
        assert reason == "latest deploy_run for YOK-772 has status=failed"

    def test_succeeded_selected_flow_allows_despite_later_other_flow_failure(
        self,
        dt_db,
    ):
        db_path, _ = dt_db
        _seed_registered_flow(db_path, flow_id="prod-flow")
        _seed_registered_flow(db_path, flow_id="stage-flow")
        _insert_item(
            db_path,
            773,
            deployment_flow="prod-flow",
            deploy_stage="complete",
            deployed_to="prod",
        )
        _seed_deploy_run(db_path, 773, "succeeded", flow="prod-flow")
        _seed_deploy_run(
            db_path,
            773,
            "failed",
            flow="stage-flow",
            created_at="2025-02-01T00:00:00Z",
        )
        allowed, reason = check_done_preconditions(773, "prod-flow", False)
        assert allowed is True
        assert reason is None
