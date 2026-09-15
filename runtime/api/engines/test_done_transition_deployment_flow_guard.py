"""done_transition deploy-flow guard: invalid-flow vs missing-evidence split."""

from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

import pytest

from yoke_core.engines import (
    done_transition,
    done_transition_deploy_gates,
    done_transition_gates,
)


def _patch_registered_flows(flows):
    return mock.patch(
        "yoke_core.domain.deployment_flow_validator.list_registered_flow_ids",
        return_value=list(flows),
    )


def _patch_target_tier(value):
    return mock.patch.object(
        done_transition_deploy_gates,
        "_read_deployment_flow_target_tier",
        return_value=value,
    )


class TestDeploymentFlowTargetTierRead:
    def test_null_target_tier_is_the_merge_only_marker(self):
        response = SimpleNamespace(success=True, result={"value": None}, error=None)
        with mock.patch.object(
            done_transition_deploy_gates,
            "call_dispatcher",
            return_value=response,
        ) as dispatch:
            result = done_transition_deploy_gates._read_deployment_flow_target_tier(
                "custom-flow", required=True
            )

        assert result == ""
        assert dispatch.call_args.kwargs["payload"] == {
            "flow_id": "custom-flow",
            "field": "target_tier",
        }

    def test_unavailable_read_is_tolerant_or_strict_by_caller(self):
        response = SimpleNamespace(
            success=False,
            result={},
            error=SimpleNamespace(message="control plane unavailable"),
        )
        with mock.patch.object(
            done_transition_deploy_gates,
            "call_dispatcher",
            return_value=response,
        ):
            assert (
                done_transition_deploy_gates._read_deployment_flow_target_tier(
                    "custom-flow", required=False
                )
                is None
            )
            with pytest.raises(
                RuntimeError,
                match="deployment_flows.get read failed: control plane unavailable",
            ):
                done_transition_deploy_gates._read_deployment_flow_target_tier(
                    "custom-flow", required=True
                )


class TestDeploymentRedirectTargetTier:
    def test_registered_merge_only_flow_bypasses_pipeline_redirect(self):
        with mock.patch.object(
            done_transition_gates,
            "_read_deployment_flow_target_tier",
            return_value="",
        ):
            result = done_transition_gates._check_deployment_redirect(
                "custom-merge", False, 500, public_ref="YOK-500"
            )
        assert result is None

    @pytest.mark.parametrize("target_tier", ["persistent", "ephemeral", None])
    def test_targeted_or_unresolved_flow_keeps_pipeline_redirect(
        self, target_tier, capsys
    ):
        with mock.patch.object(
            done_transition_gates,
            "_read_deployment_flow_target_tier",
            return_value=target_tier,
        ):
            result = done_transition_gates._check_deployment_redirect(
                "custom-flow", False, 501, public_ref="YOK-501"
            )
        assert result == 7
        assert "merge and deploy through the pipeline" in capsys.readouterr().out


class TestDeploymentFlowGuardInvalidFlow:
    def test_unregistered_flow_blocks_with_invalid_value_message(self, capsys):
        with _patch_registered_flows(["yoke-internal", "externalwebapp-prod-release"]):
            result = done_transition._check_deployment_flow_guard(
                item_id=510,
                deploy_flow="garbage",
                skip_deploy=False,
                item_project="yoke",
                old_status="implemented",
                delivery_stage_id="ship-ready",
                public_ref="YOK-510",
            )
        out = capsys.readouterr().out
        assert result == (7, "implemented")
        assert "is NOT a registered deployment flow" in out
        assert "'garbage'" in out
        assert "yoke-internal" in out
        assert "externalwebapp-prod-release" in out

    def test_literal_none_string_repro(self, capsys):
        """The literal ``none`` value surfaces invalid-value, not missing-evidence."""
        with _patch_registered_flows(["yoke-internal"]):
            result = done_transition._check_deployment_flow_guard(
                item_id=511,
                deploy_flow="none",
                skip_deploy=False,
                item_project="yoke",
                old_status="implemented",
                delivery_stage_id="ship-ready",
                public_ref="YOK-511",
            )
        out = capsys.readouterr().out
        assert result == (7, "implemented")
        assert "is NOT a registered deployment flow" in out
        assert "'none'" in out
        assert "no successful deployment evidence" not in out

    def test_unregistered_flow_message_when_registry_empty(self, capsys):
        with _patch_registered_flows([]):
            result = done_transition._check_deployment_flow_guard(
                item_id=512,
                deploy_flow="garbage",
                skip_deploy=False,
                item_project="yoke",
                old_status="implemented",
                delivery_stage_id="ship-ready",
                public_ref="YOK-512",
            )
        out = capsys.readouterr().out
        assert result == (7, "implemented")
        assert "No deployment flows are registered" in out


def _patch_latest_run(status, run_id=""):
    return mock.patch.object(
        done_transition_deploy_gates,
        "_get_latest_run_status",
        return_value=(status, run_id),
    )


def _patch_qa_gates(blocks):
    return mock.patch.object(
        done_transition_deploy_gates, "check_run_qa_gates", return_value=blocks
    )


class TestDeploymentFlowGuardRegisteredButMissingEvidence:
    def test_registered_flow_skip_deploy_no_evidence_preserves_message(self, capsys):
        with (
            _patch_registered_flows(["externalwebapp-prod-release"]),
            _patch_target_tier("persistent"),
            _patch_latest_run(""),
        ):
            result = done_transition._check_deployment_flow_guard(
                item_id=520,
                deploy_flow="externalwebapp-prod-release",
                skip_deploy=True,
                item_project="yoke",
                old_status="implemented",
                delivery_stage_id="ship-ready",
                public_ref="YOK-520",
            )
        out = capsys.readouterr().out
        assert result == (7, "implemented")
        assert "no successful deployment evidence" in out
        # Invalid-value message must not surface for a registered flow.
        assert "is NOT a registered deployment flow" not in out

    def test_registered_merge_only_flow_needs_no_deployment_evidence(self):
        with (
            _patch_registered_flows(["custom-merge"]),
            _patch_target_tier(""),
            mock.patch.object(
                done_transition_deploy_gates,
                "_check_deployment_evidence",
                side_effect=AssertionError("merge-only must not read run evidence"),
            ),
        ):
            result = done_transition._check_deployment_flow_guard(
                item_id=521,
                deploy_flow="custom-merge",
                skip_deploy=True,
                item_project="yoke",
                old_status="implemented",
                delivery_stage_id="ship-ready",
                public_ref="YOK-521",
            )
        assert result is None

    def test_internal_flow_short_circuits_before_registry_check(self):
        """Internal flows must not hit the registry check (test-flow-internal etc. are sometimes test-only)."""
        with _patch_registered_flows([]):
            result = done_transition._check_deployment_flow_guard(
                item_id=530,
                deploy_flow="yoke-internal",
                skip_deploy=False,
                item_project="yoke",
                old_status="implemented",
                delivery_stage_id="ship-ready",
                public_ref="YOK-530",
            )
        assert result is None


class TestDeploymentFlowGuardMissingFlowResolution:
    """The release-stage boundary: only a pin with a redirect target gets the
    stricter resolve-or-refuse behavior; an old pin's empty-flow merge-only
    pass-through is preserved exactly."""

    def test_old_pin_with_no_redirect_target_keeps_merge_only_pass_through(self):
        """delivery_stage_id=None means this pin never supported release-stage
        waiting; an empty flow stays today's already-satisfied merge-only."""
        with mock.patch.object(
            done_transition_deploy_gates,
            "_resolve_default_delivery_flow",
            side_effect=AssertionError("an unsupported pin must not resolve a default"),
        ):
            result = done_transition._check_deployment_flow_guard(
                item_id=540,
                deploy_flow="",
                skip_deploy=False,
                item_project="yoke",
                old_status="reviewing-implementation",
                delivery_stage_id=None,
                public_ref="YOK-540",
                workflow_id="dash",
            )
        assert result is None

    def test_resolved_default_is_frozen_onto_the_item_and_used(self, capsys):
        with (
            mock.patch.object(
                done_transition_deploy_gates,
                "_resolve_default_delivery_flow",
                return_value="externalwebapp-prod-release",
            ) as resolve,
            mock.patch.object(
                done_transition_deploy_gates,
                "_freeze_resolved_delivery_flow",
                return_value="externalwebapp-prod-release",
            ) as freeze,
            _patch_registered_flows(["externalwebapp-prod-release"]),
            _patch_target_tier(""),
        ):
            result = done_transition._check_deployment_flow_guard(
                item_id=541,
                deploy_flow="",
                skip_deploy=False,
                item_project="externalwebapp",
                old_status="reviewing-implementation",
                delivery_stage_id="release",
                public_ref="EXT-541",
                workflow_id="dash",
            )
        resolve.assert_called_once_with(
            item_project="externalwebapp", workflow_id="dash"
        )
        freeze.assert_called_once_with(
            541, "externalwebapp-prod-release", public_ref="EXT-541"
        )
        # Merge-only target tier means the resolved flow itself needs no run.
        assert result is None
        assert "is NOT a registered deployment flow" not in capsys.readouterr().out

    def test_a_value_raced_in_since_the_earlier_read_wins_over_the_resolved_default(
        self,
    ):
        """freeze_resolved_delivery_flow rereads immediately before writing;
        the guard must use ITS returned value, not the resolved default,
        when something else set a real value in between."""
        with (
            mock.patch.object(
                done_transition_deploy_gates,
                "_resolve_default_delivery_flow",
                return_value="externalwebapp-prod-release",
            ),
            mock.patch.object(
                done_transition_deploy_gates,
                "_freeze_resolved_delivery_flow",
                return_value="externalwebapp-internal",
            ),
        ):
            result = done_transition._check_deployment_flow_guard(
                item_id=543,
                deploy_flow="",
                skip_deploy=False,
                item_project="externalwebapp",
                old_status="reviewing-implementation",
                delivery_stage_id="release",
                public_ref="EXT-543",
                workflow_id="dash",
            )
        # The raced-in value is an -internal flow, so it resolves merge-only
        # rather than the resolved default's own target-tier path.
        assert result is None

    def test_nothing_resolves_refuses_with_setup_guidance(self, capsys):
        with mock.patch.object(
            done_transition_deploy_gates,
            "_resolve_default_delivery_flow",
            return_value="",
        ):
            result = done_transition._check_deployment_flow_guard(
                item_id=542,
                deploy_flow="",
                skip_deploy=False,
                item_project="externalwebapp",
                old_status="reviewing-implementation",
                delivery_stage_id="release",
                public_ref="EXT-542",
                workflow_id="dash",
            )
        out = capsys.readouterr().out
        assert result == (7, "reviewing-implementation")
        assert "no deployment flow selected" in out
        assert "no workflow-specific or project-wide delivery default" in out
