"""Field validation and result-type tests for yoke_core.domain.mutations —
deployment_flow project validation, deployed_to validation, and result type structures."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from yoke_core.domain.mutations import (
    ApprovalResult,
    CreateResult,
    GateContext,
    ItemState,
    MutationResult,
    prepare_update,
)


def _make_item(**overrides) -> ItemState:
    defaults = dict(
        id=42,
        title="Test item",
        item_type="issue",
        status="idea",
        priority="medium",
        rework_count=0,
        frozen=False,
        project="yoke",
    )
    defaults.update(overrides)
    return ItemState(**defaults)


def _make_gate(**overrides) -> GateContext:
    return GateContext(**overrides)


class TestDeploymentFlowValidation:
    def test_flow_project_mismatch(self):
        item = _make_item(project="yoke")
        gate = _make_gate(flow_project="externalwebapp")
        result = prepare_update(
            item=item, field_name="deployment_flow",
            value="externalwebapp-flow", gate=gate,
        )
        assert result.success is False

    def test_flow_project_match(self):
        item = _make_item(project="yoke")
        gate = _make_gate(flow_project="yoke")
        result = prepare_update(
            item=item, field_name="deployment_flow",
            value="yoke-flow", gate=gate,
        )
        assert result.success is True

    def test_flow_null_no_validation(self):
        item = _make_item(project="yoke")
        result = prepare_update(
            item=item, field_name="deployment_flow",
            value=None,
        )
        assert result.success is True


class TestDeployedToValidation:
    def test_valid_env(self):
        item = _make_item(project="externalwebapp")
        gate = _make_gate(valid_deploy_envs=["staging", "production"])
        result = prepare_update(
            item=item, field_name="deployed_to",
            value="staging", gate=gate,
        )
        assert result.success is True

    def test_invalid_env(self):
        item = _make_item(project="externalwebapp")
        gate = _make_gate(valid_deploy_envs=["staging", "production"])
        result = prepare_update(
            item=item, field_name="deployed_to",
            value="dev", gate=gate,
        )
        assert result.success is False
        assert "dev" in result.error

    def test_no_envs_configured(self):
        item = _make_item(project="externalwebapp")
        gate = _make_gate(valid_deploy_envs=[])
        result = prepare_update(
            item=item, field_name="deployed_to",
            value="staging", gate=gate,
        )
        assert result.success is False
        assert "No deployment environments" in result.error

    def test_null_value_no_validation(self):
        item = _make_item(project="externalwebapp")
        gate = _make_gate(valid_deploy_envs=["staging"])
        result = prepare_update(
            item=item, field_name="deployed_to",
            value=None, gate=gate,
        )
        assert result.success is True


class TestResultTypes:
    def test_mutation_result_defaults(self):
        r = MutationResult(success=True)
        assert r.events == ()
        assert r.field_writes == {}
        assert r.item_id is None

    def test_create_result_has_defaults(self):
        r = CreateResult(success=True, defaults={"status": "idea"})
        assert r.defaults["status"] == "idea"

    def test_approval_result_fields(self):
        r = ApprovalResult(
            success=True,
            next_stage="deploy",
            run_id="run-1",
            member_item_ids=(1, 2),
            approved_at="2026-01-01T00:00:00Z",
        )
        assert r.next_stage == "deploy"
        assert r.member_item_ids == (1, 2)
