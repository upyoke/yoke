"""Each closure path that reaches the deployment-flow guard reads the QA gate.

Split from ``test_done_transition_deployment_flow_guard.py``, whose patch
helpers these reuse, to keep both files inside the authored line budget.
That file covers which flows the guard treats as merge-only and how it
resolves a delivery default; this one covers the paths that carry an item
past the guard, and what each of them asks the QA gate.
"""

from __future__ import annotations

from unittest import mock

from runtime.api.engines.test_done_transition_deployment_flow_guard import (
    _patch_latest_run,
    _patch_qa_gates,
    _patch_registered_flows,
    _patch_target_tier,
)
from yoke_core.engines import done_transition


class TestDeploymentFlowGuardQaAuthorities:
    """Every closure path that reaches the guard consults the QA gate.

    ``--skip-deploy`` waives re-running the pipeline, not the verdicts
    the evidence it accepts is supposed to carry, and the runless
    ``deploy_stage=complete`` fallback is a closure path like any other.
    """

    def test_skip_deploy_with_evidence_still_honours_unsatisfied_qa(self):
        with (
            _patch_registered_flows(["acme-prod"]),
            _patch_target_tier("persistent"),
            _patch_latest_run("succeeded", "run-7"),
            _patch_qa_gates(True) as gate,
        ):
            result = done_transition._check_deployment_flow_guard(
                item_id=530,
                deploy_flow="acme-prod",
                skip_deploy=True,
                item_project="yoke",
                old_status="release",
                delivery_stage_id="release",
                public_ref="YOK-530",
            )
        assert result == (7, "release")
        gate.assert_called_once_with(530, "run-7")

    def test_skip_deploy_with_satisfied_qa_proceeds(self):
        with (
            _patch_registered_flows(["acme-prod"]),
            _patch_target_tier("persistent"),
            _patch_latest_run("succeeded", "run-7"),
            _patch_qa_gates(False),
        ):
            result = done_transition._check_deployment_flow_guard(
                item_id=531,
                deploy_flow="acme-prod",
                skip_deploy=True,
                item_project="yoke",
                old_status="release",
                delivery_stage_id="release",
                public_ref="YOK-531",
            )
        assert result is None

    def test_the_runless_complete_fallback_honours_unsatisfied_qa(self):
        with (
            _patch_registered_flows(["acme-prod"]),
            _patch_target_tier("persistent"),
            _patch_latest_run("unexpected-status", "run-8"),
            _patch_qa_gates(True) as gate,
            mock.patch.object(
                done_transition,
                "_query_item_field",
                return_value="complete",
            ),
        ):
            result = done_transition._check_deployment_flow_guard(
                item_id=532,
                deploy_flow="acme-prod",
                skip_deploy=False,
                item_project="yoke",
                old_status="release",
                delivery_stage_id="release",
                public_ref="YOK-532",
            )
        assert result == (7, "release")
        gate.assert_called_once_with(532, "run-8")
