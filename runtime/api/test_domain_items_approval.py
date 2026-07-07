"""Tests for yoke_core.domain.approval — canonical invariants, halt-state
helpers, halt resolution, flow-stage parsing, approval resolution, and ApprovalPath."""

from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from yoke_core.domain.approval import (
    APPROVAL_SCOPE,
    HALT_RESOLUTION,
    STAGE_AUTHORITY_FIELD,
    STAGE_CACHE_FIELD,
    ApprovalAction,
    ApprovalPath,
    HaltState,
    find_stage_index,
    is_approval_action,
    is_halt_state,
    is_human_approval_stage,
    parse_flow_stages,
    resolve_approval,
    resolve_halt_state,
)


class TestApprovalParity:
    """Prove the shared approval vocabulary stays on its canonical values."""

    def test_approval_scope_match(self):
        assert APPROVAL_SCOPE == "shared"

    def test_halt_states_match(self):
        python_states = {h.value for h in HaltState}
        assert python_states == {"awaiting-approval", "needs-capability"}

    def test_approval_actions_match(self):
        python_actions = {a.value for a in ApprovalAction}
        assert python_actions == {"approve", "provide-capability"}

    def test_stage_authority_field_match(self):
        assert STAGE_AUTHORITY_FIELD == "current_stage"

    def test_stage_cache_field_match(self):
        assert STAGE_CACHE_FIELD == "deploy_stage"


class TestHaltStateHelpers:
    """Test halt-state recognition and resolution."""

    @pytest.mark.parametrize("state,expected", [
        ("awaiting-approval", True),
        ("needs-capability", True),
        ("active", False),
        ("done", False),
        ("", False),
    ])
    def test_is_halt_state(self, state: str, expected: bool):
        assert is_halt_state(state) == expected

    @pytest.mark.parametrize("action,expected", [
        ("approve", True),
        ("provide-capability", True),
        ("reject", False),
        ("cancel", False),
        ("", False),
    ])
    def test_is_approval_action(self, action: str, expected: bool):
        assert is_approval_action(action) == expected

    def test_halt_state_helper_matches_canonical_set(self):
        test_values = ["awaiting-approval", "needs-capability", "active", "done", "unknown"]
        for val in test_values:
            assert is_halt_state(val) == (val in {"awaiting-approval", "needs-capability"})

    def test_approval_action_helper_matches_canonical_set(self):
        test_values = ["approve", "provide-capability", "reject", "cancel", "unknown"]
        for val in test_values:
            assert is_approval_action(val) == (val in {"approve", "provide-capability"})


class TestHaltResolution:
    """Test halt-state to action resolution mapping."""

    def test_awaiting_approval_resolves_to_approve(self):
        assert resolve_halt_state("awaiting-approval") == "approve"

    def test_needs_capability_resolves_to_provide_capability(self):
        assert resolve_halt_state("needs-capability") == "provide-capability"

    def test_unknown_halt_returns_none(self):
        assert resolve_halt_state("active") is None
        assert resolve_halt_state("") is None

    def test_resolution_map_completeness(self):
        """Every halt state has a resolution action."""
        for halt in HaltState:
            assert halt in HALT_RESOLUTION
            assert isinstance(HALT_RESOLUTION[halt], ApprovalAction)


_SAMPLE_STAGES_JSON = json.dumps([
    {"name": "merged", "executor": "auto"},
    {"name": "approve-deploy", "executor": "human-approval"},
    {"name": "prod-deploy", "executor": "github-actions-workflow", "workflow": "deploy.yml"},
    {"name": "complete", "executor": "auto"},
])


class TestFlowStageParsing:
    """Test parse_flow_stages and related helpers."""

    def test_parse_stages(self):
        stages = parse_flow_stages(_SAMPLE_STAGES_JSON)
        assert len(stages) == 4
        assert stages[0].name == "merged"
        assert stages[0].executor == "auto"
        assert stages[1].name == "approve-deploy"
        assert stages[1].executor == "human-approval"
        assert stages[2].config == {"workflow": "deploy.yml"}

    def test_find_stage_index(self):
        stages = parse_flow_stages(_SAMPLE_STAGES_JSON)
        assert find_stage_index(stages, "merged") == 0
        assert find_stage_index(stages, "approve-deploy") == 1
        assert find_stage_index(stages, "prod-deploy") == 2
        assert find_stage_index(stages, "complete") == 3
        assert find_stage_index(stages, "nonexistent") is None

    def test_is_human_approval_stage(self):
        stages = parse_flow_stages(_SAMPLE_STAGES_JSON)
        assert is_human_approval_stage(stages[0]) is False
        assert is_human_approval_stage(stages[1]) is True
        assert is_human_approval_stage(stages[2]) is False


class TestApprovalResolution:
    """Test resolve_approval behavior."""

    def test_approve_at_human_approval_stage(self):
        stages = parse_flow_stages(_SAMPLE_STAGES_JSON)
        result = resolve_approval(stages, "approve-deploy")
        assert result.approved is True
        assert result.next_stage == "prod-deploy"
        assert result.error is None

    def test_reject_at_non_approval_stage(self):
        stages = parse_flow_stages(_SAMPLE_STAGES_JSON)
        result = resolve_approval(stages, "merged")
        assert result.approved is False
        assert result.next_stage is None
        assert "not a human-approval stage" in result.error

    def test_reject_unknown_stage(self):
        stages = parse_flow_stages(_SAMPLE_STAGES_JSON)
        result = resolve_approval(stages, "nonexistent")
        assert result.approved is False
        assert "does not match any stage" in result.error

    def test_approve_at_last_stage_returns_complete(self):
        """If the approval is at the last stage, next_stage should be 'complete'."""
        stages_json = json.dumps([
            {"name": "final-approval", "executor": "human-approval"},
        ])
        stages = parse_flow_stages(stages_json)
        result = resolve_approval(stages, "final-approval")
        assert result.approved is True
        assert result.next_stage == "complete"

    def test_approve_at_second_to_last_stage(self):
        """Approval at second-to-last stage advances to the last stage."""
        stages_json = json.dumps([
            {"name": "build", "executor": "auto"},
            {"name": "gate", "executor": "human-approval"},
            {"name": "deploy", "executor": "github-actions-workflow"},
        ])
        stages = parse_flow_stages(stages_json)
        result = resolve_approval(stages, "gate")
        assert result.approved is True
        assert result.next_stage == "deploy"


class TestApprovalPath:
    """Test approval path type enum."""

    def test_yoke_handled(self):
        assert ApprovalPath.YOKE_HANDLED.value == "yoke-handled"

    def test_external(self):
        assert ApprovalPath.EXTERNAL.value == "external"
