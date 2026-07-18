"""done_transition deploy-flow guard: invalid-flow vs missing-evidence split."""

from __future__ import annotations

from unittest import mock

from yoke_core.engines import done_transition, done_transition_deploy_gates


def _patch_registered_flows(flows):
    return mock.patch(
        "yoke_core.domain.deployment_flow_validator.list_registered_flow_ids",
        return_value=list(flows),
    )


class TestDeploymentFlowGuardInvalidFlow:
    def test_unregistered_flow_blocks_with_invalid_value_message(self, capsys):
        with _patch_registered_flows(["yoke-internal", "externalwebapp-prod-release"]):
            result = done_transition._check_deployment_flow_guard(
                item_id=510,
                deploy_flow="garbage",
                skip_deploy=False,
                item_project="yoke",
                old_status="implemented",
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
            )
        out = capsys.readouterr().out
        assert result == (7, "implemented")
        assert "No deployment flows are registered" in out


class TestDeploymentFlowGuardRegisteredButMissingEvidence:
    def test_registered_flow_skip_deploy_no_evidence_preserves_message(self, capsys):
        with _patch_registered_flows(["externalwebapp-prod-release"]), mock.patch.object(
            done_transition_deploy_gates,
            "_check_deployment_evidence",
            return_value=False,
        ):
            result = done_transition._check_deployment_flow_guard(
                item_id=520,
                deploy_flow="externalwebapp-prod-release",
                skip_deploy=True,
                item_project="yoke",
                old_status="implemented",
            )
        out = capsys.readouterr().out
        assert result == (7, "implemented")
        assert "no successful deployment evidence" in out
        # Invalid-value message must not surface for a registered flow.
        assert "is NOT a registered deployment flow" not in out

    def test_internal_flow_short_circuits_before_registry_check(self):
        """Internal flows must not hit the registry check (test-flow-internal etc. are sometimes test-only)."""
        with _patch_registered_flows([]):
            result = done_transition._check_deployment_flow_guard(
                item_id=530,
                deploy_flow="yoke-internal",
                skip_deploy=False,
                item_project="yoke",
                old_status="implemented",
            )
        assert result is None
