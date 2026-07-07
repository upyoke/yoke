"""Status transition, rework detection, and done-cleanup tests for yoke_core.domain.mutations."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from yoke_core.domain.mutations import (
    GateContext,
    ItemState,
    MutationEventKind,
    prepare_update,
)

TEST_ITEM_ID = 42
TEST_ITEM_REF = f"YOK-{TEST_ITEM_ID}"


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


class TestStatusTransition:
    def test_valid_status_epic(self):
        """Epic items accept epic-workflow-type statuses."""
        item = _make_item(item_type="epic", status="idea")
        gate = _make_gate(done_nonce_verified=True)
        result = prepare_update(item=item, field_name="status", value="planning", gate=gate)
        assert result.success is True
        assert result.field_writes["status"] == "planning"
        assert any(
            e.kind == MutationEventKind.STATUS_TRANSITIONED for e in result.events
        )

    def test_valid_status_issue(self):
        """Issue items accept issue-workflow-type statuses."""
        item = _make_item(item_type="issue", status="idea")
        gate = _make_gate(done_nonce_verified=True)
        result = prepare_update(item=item, field_name="status", value="refining-idea", gate=gate)
        assert result.success is True
        assert result.field_writes["status"] == "refining-idea"

    def test_invalid_status(self):
        item = _make_item(item_type="epic")
        result = prepare_update(item=item, field_name="status", value="bogus")
        assert result.success is False
        assert result.error_code == "VALIDATION_ERROR"

    def test_issue_rejects_shared_only_status(self):
        """FR-3: Issue items reject legacy shared-only statuses."""
        item = _make_item(item_type="issue", status="idea")
        for legacy in ("defined", "designed", "planned", "ready", "active",
                        "review", "validate", "passed"):
            result = prepare_update(
                item=item, field_name="status", value=legacy,
            )
            assert result.success is False, f"Expected rejection of '{legacy}' for issue"
            assert result.error_code == "VALIDATION_ERROR"
            assert "issue-workflow-type lifecycle" in result.error

    def test_issue_accepts_issue_family_statuses(self):
        """FR-3: Issue items accept all issue-workflow-type statuses."""
        gate = _make_gate(
            done_nonce_verified=True,
            qa_requirement_count=1,
            unsatisfied_verification_blocking=0,
        )
        for status in ("refining-idea", "refined-idea", "implementing",
                        "reviewing-implementation", "reviewed-implementation",
                        "polishing-implementation",
                        "implemented", "release"):
            item = _make_item(item_type="issue", status="idea")
            result = prepare_update(
                item=item, field_name="status", value=status, gate=gate,
            )
            assert result.success is True, f"Expected acceptance of '{status}' for issue"

    def test_issue_accepts_exceptional_statuses(self):
        """FR-3: Issue items accept exceptional statuses."""
        gate = _make_gate(done_nonce_verified=True)
        for status in ("blocked", "stopped", "failed", "cancelled"):
            item = _make_item(item_type="issue", status="idea")
            result = prepare_update(
                item=item, field_name="status", value=status, gate=gate,
            )
            assert result.success is True, f"Expected acceptance of '{status}' for issue"

    def test_epic_accepts_epic_family_statuses(self):
        """FR-3: Epic items accept epic-workflow-type lifecycle statuses."""
        gate = _make_gate(
            done_nonce_verified=True,
            has_merged_at=True,
            qa_requirement_count=1,
            unsatisfied_verification_blocking=0,
        )
        # Exclude done (needs special gates) — test the epic-workflow-type progression
        for status in ("refining-idea", "refined-idea", "planning", "plan-drafted",
                        "refining-plan", "planned", "implementing",
                        "reviewing-implementation", "reviewed-implementation",
                        "polishing-implementation",
                        "implemented", "release"):
            item = _make_item(item_type="epic", status="idea")
            result = prepare_update(
                item=item, field_name="status", value=status, gate=gate,
            )
            assert result.success is True, f"Expected acceptance of '{status}' for epic"

    def test_epic_rejects_legacy_shared_only_statuses(self):
        """FR-3: Epic items reject legacy shared-only statuses."""
        item = _make_item(item_type="epic", status="idea")
        for legacy in ("defined", "designed", "ready", "active",
                        "review", "validate", "passed"):
            result = prepare_update(
                item=item, field_name="status", value=legacy,
            )
            assert result.success is False, f"Expected rejection of '{legacy}' for epic"
            assert result.error_code == "VALIDATION_ERROR"
            assert "epic-workflow-type lifecycle" in result.error

    def test_epic_accepts_exceptional_statuses(self):
        """FR-3: Epic items accept exceptional statuses."""
        gate = _make_gate(done_nonce_verified=True)
        for status in ("blocked", "stopped", "failed", "cancelled"):
            item = _make_item(item_type="epic", status="idea")
            result = prepare_update(
                item=item, field_name="status", value=status, gate=gate,
            )
            assert result.success is True, f"Expected acceptance of '{status}' for epic"

    def test_epic_accepts_idea_backward_compat(self):
        """AC-7: Epic items accept 'idea' (backward compatibility)."""
        item = _make_item(item_type="epic", status="planning")
        gate = _make_gate(done_nonce_verified=True)
        result = prepare_update(
            item=item, field_name="status", value="idea", gate=gate,
        )
        assert result.success is True

    def test_forward_transition_flag(self):
        item = _make_item(item_type="epic", status="idea")
        gate = _make_gate(done_nonce_verified=True)
        result = prepare_update(item=item, field_name="status", value="implementing", gate=gate)
        assert result.success is True
        event = [e for e in result.events if e.kind == MutationEventKind.STATUS_TRANSITIONED][0]
        assert event.detail["is_forward"] is True

    def test_backward_transition_flag(self):
        item = _make_item(item_type="epic", status="implementing")
        gate = _make_gate(done_nonce_verified=True)
        result = prepare_update(item=item, field_name="status", value="idea", gate=gate)
        assert result.success is True
        event = [e for e in result.events if e.kind == MutationEventKind.STATUS_TRANSITIONED][0]
        assert event.detail["is_forward"] is False

    def test_forward_transition_flag_issue_item_passes_item_type(self, monkeypatch):
        """Issue-item transition metadata forwards item_type to the lifecycle helper."""

        captured = {}

        def fake_is_forward_transition(from_status, to_status, *, item_type=None):
            captured["call"] = (from_status, to_status, item_type)
            return True

        monkeypatch.setattr(
            "yoke_core.domain.mutations.is_forward_transition",
            fake_is_forward_transition,
        )

        item = _make_item(item_type="issue", status="idea")
        gate = _make_gate(done_nonce_verified=True)
        result = prepare_update(
            item=item, field_name="status", value="implementing", gate=gate,
        )

        assert result.success is True
        assert captured["call"] == ("idea", "implementing", "issue")
        event = [e for e in result.events if e.kind == MutationEventKind.STATUS_TRANSITIONED][0]
        assert event.detail["is_forward"] is True


class TestReworkDetection:
    def test_done_to_implementing_increments_rework(self):
        item = _make_item(item_type="issue", status="done", rework_count=1)
        gate = _make_gate(done_nonce_verified=True)
        result = prepare_update(item=item, field_name="status", value="implementing", gate=gate)
        assert result.success is True
        assert result.field_writes["rework_count"] == 2
        assert any(
            e.kind == MutationEventKind.REWORK_INCREMENTED for e in result.events
        )

    def test_reviewed_to_implementing_increments_rework(self):
        item = _make_item(item_type="issue", status="reviewed-implementation", rework_count=0)
        gate = _make_gate(done_nonce_verified=True)
        result = prepare_update(item=item, field_name="status", value="implementing", gate=gate)
        assert result.success is True
        assert result.field_writes["rework_count"] == 1

    def test_idea_to_implementing_no_rework(self):
        item = _make_item(item_type="issue", status="idea")
        gate = _make_gate(done_nonce_verified=True)
        result = prepare_update(item=item, field_name="status", value="implementing", gate=gate)
        assert result.success is True
        assert "rework_count" not in result.field_writes


class TestDoneCleanup:
    def test_done_clears_fields(self):
        item = _make_item(
            item_type="epic",
            status="implementing",
            frozen=True,
            worktree=TEST_ITEM_REF,
        )
        gate = _make_gate(done_nonce_verified=True, has_merged_at=True)
        result = prepare_update(item=item, field_name="status", value="done", gate=gate)
        assert result.success is True
        assert result.field_writes["frozen"] is False
        assert result.field_writes["worktree"] is None
        assert any(e.kind == MutationEventKind.DONE_CLEANUP for e in result.events)

    def test_non_done_no_cleanup(self):
        item = _make_item(item_type="epic", status="idea")
        gate = _make_gate(done_nonce_verified=True)
        result = prepare_update(item=item, field_name="status", value="implementing", gate=gate)
        assert result.success is True
        assert "worktree" not in result.field_writes
