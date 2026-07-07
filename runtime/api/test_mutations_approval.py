"""Approval-apply mutation tests for yoke_core.domain.mutations."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from yoke_core.domain.mutations import (
    GateContext,
    ItemState,
    MutationEventKind,
    prepare_approval,
)
from yoke_core.domain.approval import FlowStage
from yoke_core.domain.runs import DeploymentRun


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


class TestPrepareApproval:
    def _make_flow_stages(self):
        """Create a typical 3-stage flow."""
        return [
            FlowStage(name="build", executor="github-actions", config={}),
            FlowStage(name="staging-gate", executor="human-approval", config={}),
            FlowStage(name="deploy-prod", executor="github-actions", config={}),
        ]

    def test_successful_approval(self):
        item = _make_item(
            deploy_stage="staging-gate",
            deployment_flow="main-flow",
            status="release",
        )
        stages = self._make_flow_stages()
        run = DeploymentRun(
            id="run-123", project="yoke", flow="main-flow",
            status="executing", current_stage="staging-gate",
        )
        result = prepare_approval(
            item=item,
            flow_stages=stages,
            active_run=run,
            member_item_ids=[42, 43],
        )
        assert result.success is True
        assert result.next_stage == "deploy-prod"
        assert result.run_id == "run-123"
        assert result.member_item_ids == (42, 43)
        assert result.approved_at is not None
        assert result.field_writes["deploy_stage"] == "deploy-prod"
        assert result.field_writes["status"] == "release"
        assert any(e.kind == MutationEventKind.APPROVAL_APPLIED for e in result.events)
        assert any(e.kind == MutationEventKind.RUN_STAGE_ADVANCED for e in result.events)
        assert any(e.kind == MutationEventKind.MEMBER_STAGE_SYNCED for e in result.events)

    def test_approval_no_deploy_stage(self):
        item = _make_item(deploy_stage=None, deployment_flow="main-flow")
        result = prepare_approval(
            item=item, flow_stages=[], active_run=None, member_item_ids=[],
        )
        assert result.success is False
        assert result.error_code == "INVALID_STATE"
        assert "deploy_stage" in result.error

    def test_approval_no_deployment_flow(self):
        item = _make_item(deploy_stage="staging-gate", deployment_flow=None)
        result = prepare_approval(
            item=item, flow_stages=[], active_run=None, member_item_ids=[],
        )
        assert result.success is False
        assert "deployment_flow" in result.error

    def test_approval_stage_not_human_approval(self):
        item = _make_item(
            deploy_stage="build",
            deployment_flow="main-flow",
        )
        stages = self._make_flow_stages()
        result = prepare_approval(
            item=item, flow_stages=stages, active_run=None, member_item_ids=[],
        )
        assert result.success is False
        assert "human-approval" in result.error

    def test_approval_no_active_run(self):
        """Approval without an active run still succeeds (item-only update)."""
        item = _make_item(
            deploy_stage="staging-gate",
            deployment_flow="main-flow",
        )
        stages = self._make_flow_stages()
        result = prepare_approval(
            item=item, flow_stages=stages, active_run=None, member_item_ids=[],
        )
        assert result.success is True
        assert result.run_id is None
        assert result.next_stage == "deploy-prod"
        # No run-level events when there is no active run
        assert not any(
            e.kind == MutationEventKind.RUN_STAGE_ADVANCED for e in result.events
        )

    def test_approval_last_stage(self):
        """Approval at the last stage returns 'complete'."""
        stages = [
            FlowStage(name="final-gate", executor="human-approval", config={}),
        ]
        item = _make_item(
            deploy_stage="final-gate",
            deployment_flow="main-flow",
        )
        result = prepare_approval(
            item=item, flow_stages=stages, active_run=None, member_item_ids=[],
        )
        assert result.success is True
        assert result.next_stage == "complete"
