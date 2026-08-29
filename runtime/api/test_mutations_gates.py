"""Gate tests for yoke_core.domain.mutations — epic task gate, done-ceremony nonce,
epic merge gate, QA gates, and combined-gate scenarios."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from yoke_core.domain.mutations import (
    GateContext,
    ItemState,
    prepare_update,
)
from yoke_core.domain.workflow_runtime import builtin_workflow_runtime


def _make_item(**overrides) -> ItemState:
    defaults = dict(
        id=42,
        title="Test item",
        status="idea",
        priority="medium",
        frozen=False,
        project="yoke",
    )
    defaults.update(overrides)
    workflow_id = defaults.pop("workflow", "issue")
    defaults["workflow"] = builtin_workflow_runtime(workflow_id)
    return ItemState(**defaults)


def _make_gate(**overrides) -> GateContext:
    return GateContext(**overrides)


class TestEpicTaskGate:
    def test_epic_ready_rejected_by_validation(self):
        """Epic items reject 'ready' (legacy shared-only status)
        before the epic task gate is even reached."""
        item = _make_item(workflow="epic")
        gate = _make_gate(epic_task_count=0, done_nonce_verified=True)
        result = prepare_update(
            item=item, field_name="status", value="ready", gate=gate
        )
        assert result.success is False
        assert result.error_code == "VALIDATION_ERROR"

    def test_epic_active_rejected_by_validation(self):
        """Epic items reject 'active' (legacy shared-only status)
        before the epic task gate is even reached."""
        item = _make_item(workflow="epic")
        gate = _make_gate(epic_task_count=0, done_nonce_verified=True)
        result = prepare_update(
            item=item, field_name="status", value="active", gate=gate
        )
        assert result.success is False
        assert result.error_code == "VALIDATION_ERROR"

    def test_issue_ready_rejected(self):
        """Issue items reject 'ready' (shared-only status)."""
        item = _make_item(workflow="issue")
        gate = _make_gate(done_nonce_verified=True)
        result = prepare_update(
            item=item, field_name="status", value="ready", gate=gate
        )
        assert result.success is False
        assert result.error_code == "VALIDATION_ERROR"


class TestDoneNonceGate:
    def test_done_blocked_without_nonce(self):
        item = _make_item(workflow="epic", status="implementing")
        gate = _make_gate(done_nonce_verified=False, force=False)
        result = prepare_update(item=item, field_name="status", value="done", gate=gate)
        assert result.success is False
        assert result.error_code == "GATE_DONE_NONCE"

    def test_done_allowed_with_nonce(self):
        item = _make_item(workflow="epic", status="implementing")
        gate = _make_gate(done_nonce_verified=True, has_merged_at=True)
        result = prepare_update(item=item, field_name="status", value="done", gate=gate)
        assert result.success is True

    def test_done_allowed_with_force(self):
        item = _make_item(workflow="epic", status="implementing")
        gate = _make_gate(done_nonce_verified=False, force=True, has_merged_at=True)
        result = prepare_update(item=item, field_name="status", value="done", gate=gate)
        assert result.success is True


class TestEpicMergeGate:
    def test_epic_done_blocked_no_merged_at(self):
        item = _make_item(workflow="epic", status="implementing")
        gate = _make_gate(has_merged_at=False, done_nonce_verified=True)
        result = prepare_update(item=item, field_name="status", value="done", gate=gate)
        assert result.success is False
        assert result.error_code == "GATE_EPIC_MERGE"

    def test_epic_done_allowed_with_merged_at(self):
        item = _make_item(workflow="epic", status="implementing")
        gate = _make_gate(has_merged_at=True, done_nonce_verified=True)
        result = prepare_update(item=item, field_name="status", value="done", gate=gate)
        assert result.success is True

    def test_epic_done_force_override(self):
        item = _make_item(workflow="epic", status="implementing")
        gate = _make_gate(has_merged_at=False, done_nonce_verified=True, force=True)
        result = prepare_update(item=item, field_name="status", value="done", gate=gate)
        assert result.success is True

    def test_issue_done_no_merge_gate(self):
        item = _make_item(workflow="issue", status="implementing")
        gate = _make_gate(has_merged_at=False, done_nonce_verified=True)
        result = prepare_update(item=item, field_name="status", value="done", gate=gate)
        assert result.success is True


class TestQAGates:
    def test_reviewing_blocked_no_requirements(self):
        item = _make_item(workflow="issue", status="implementing")
        gate = _make_gate(qa_requirement_count=0)
        result = prepare_update(
            item=item,
            field_name="status",
            value="reviewing-implementation",
            gate=gate,
        )
        assert result.success is False
        assert result.error_code == "GATE_QA_REVIEWING"

    def test_reviewing_allowed_with_requirements(self):
        item = _make_item(workflow="issue", status="implementing")
        gate = _make_gate(qa_requirement_count=2)
        result = prepare_update(
            item=item,
            field_name="status",
            value="reviewing-implementation",
            gate=gate,
        )
        assert result.success is True

    def test_implemented_blocked_unsatisfied(self):
        item = _make_item(workflow="issue", status="reviewed-implementation")
        gate = _make_gate(
            unsatisfied_verification_blocking=2,
            done_nonce_verified=True,
        )
        result = prepare_update(
            item=item,
            field_name="status",
            value="implemented",
            gate=gate,
        )
        assert result.success is False
        assert result.error_code == "GATE_QA_IMPLEMENTED"

    def test_implemented_allowed_all_satisfied(self):
        item = _make_item(workflow="issue", status="reviewed-implementation")
        gate = _make_gate(
            unsatisfied_verification_blocking=0,
            done_nonce_verified=True,
        )
        result = prepare_update(
            item=item,
            field_name="status",
            value="implemented",
            gate=gate,
        )
        assert result.success is True

    def test_release_blocked_unsatisfied_verification(self):
        item = _make_item(workflow="issue", status="implemented")
        gate = _make_gate(
            unsatisfied_verification_blocking=2,
            done_nonce_verified=True,
        )
        result = prepare_update(
            item=item,
            field_name="status",
            value="release",
            gate=gate,
        )
        assert result.success is False
        assert result.error_code == "GATE_QA_RELEASE"

    def test_release_allowed_all_verified(self):
        item = _make_item(workflow="issue", status="implemented")
        gate = _make_gate(
            unsatisfied_verification_blocking=0,
            done_nonce_verified=True,
        )
        result = prepare_update(
            item=item,
            field_name="status",
            value="release",
            gate=gate,
        )
        assert result.success is True

    def test_done_blocked_unsatisfied_qa(self):
        item = _make_item(workflow="issue", status="implemented")
        gate = _make_gate(
            unsatisfied_all_blocking=1,
            done_nonce_verified=True,
        )
        result = prepare_update(item=item, field_name="status", value="done", gate=gate)
        assert result.success is False
        assert result.error_code == "GATE_QA_DONE"

    def test_done_allowed_qa_satisfied(self):
        item = _make_item(workflow="issue", status="implemented")
        gate = _make_gate(
            unsatisfied_all_blocking=0,
            done_nonce_verified=True,
        )
        result = prepare_update(item=item, field_name="status", value="done", gate=gate)
        assert result.success is True

    def test_qa_bypass_skips_gates(self):
        item = _make_item(workflow="issue", status="implementing")
        gate = _make_gate(
            qa_requirement_count=0,
            qa_bypass=True,
            done_nonce_verified=True,
        )
        result = prepare_update(
            item=item,
            field_name="status",
            value="reviewing-implementation",
            gate=gate,
        )
        assert result.success is True

    def test_force_skips_qa_gates(self):
        item = _make_item(workflow="issue", status="implementing")
        gate = _make_gate(
            qa_requirement_count=0,
            force=True,
            done_nonce_verified=True,
        )
        result = prepare_update(
            item=item,
            field_name="status",
            value="reviewing-implementation",
            gate=gate,
        )
        assert result.success is True


class TestCombinedGateScenarios:
    def test_epic_done_needs_all_gates(self):
        """Epic -> done requires nonce + merge + QA."""
        item = _make_item(workflow="epic", status="implementing")
        # Missing nonce
        gate = _make_gate(
            has_merged_at=True,
            done_nonce_verified=False,
            unsatisfied_all_blocking=0,
        )
        result = prepare_update(item=item, field_name="status", value="done", gate=gate)
        assert result.success is False
        assert result.error_code == "GATE_DONE_NONCE"

    def test_epic_done_nonce_ok_merge_fails(self):
        item = _make_item(workflow="epic", status="implementing")
        gate = _make_gate(
            has_merged_at=False,
            done_nonce_verified=True,
            unsatisfied_all_blocking=0,
        )
        result = prepare_update(item=item, field_name="status", value="done", gate=gate)
        assert result.success is False
        assert result.error_code == "GATE_EPIC_MERGE"
