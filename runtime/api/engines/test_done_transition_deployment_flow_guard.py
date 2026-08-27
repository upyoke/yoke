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
                "custom-merge", False, 500, item_ref="YOK-500"
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
                "custom-flow", False, 501, item_ref="YOK-501"
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
                item_ref="YOK-510",
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
                item_ref="YOK-511",
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
                item_ref="YOK-512",
            )
        out = capsys.readouterr().out
        assert result == (7, "implemented")
        assert "No deployment flows are registered" in out


class TestDeploymentFlowGuardRegisteredButMissingEvidence:
    def test_registered_flow_skip_deploy_no_evidence_preserves_message(self, capsys):
        with (
            _patch_registered_flows(["externalwebapp-prod-release"]),
            _patch_target_tier("persistent"),
            mock.patch.object(
                done_transition_deploy_gates,
                "_check_deployment_evidence",
                return_value=False,
            ),
        ):
            result = done_transition._check_deployment_flow_guard(
                item_id=520,
                deploy_flow="externalwebapp-prod-release",
                skip_deploy=True,
                item_project="yoke",
                old_status="implemented",
                delivery_stage_id="ship-ready",
                item_ref="YOK-520",
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
                item_ref="YOK-521",
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
                item_ref="YOK-530",
            )
        assert result is None
