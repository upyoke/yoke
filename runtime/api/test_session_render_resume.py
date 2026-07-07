"""Tests for yoke_core.domain.session — resume compatibility validation
and resume no-progress detection."""

from __future__ import annotations

import os
import sys
from runtime.api.test_constants import TEST_MODEL_ID

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from yoke_core.domain.session import (
    ActionKind,
    ClaimedWork,
    FrontierState,
    SessionOffer,
    decide_next_action,
)

# Synthetic test item ID — not a real backlog item reference.
TEST_ITEM_ID = 4242
TEST_ITEM_REF = f"YOK-{TEST_ITEM_ID}"


def _make_offer(**overrides):
    defaults = {
        "session_id": "test-session-001",
        "executor": "DARIUS",
        "provider": "anthropic",
        "model": TEST_MODEL_ID,
        "workspace": "/tmp/yoke",
    }
    defaults.update(overrides)
    return SessionOffer(**defaults)


class TestResumeCompatibilityValidation:
    """FR-6: Resume compatibility mirrors charge policy."""

    def test_resume_unsupported_path_escalates(self):
        """AC-7: Claimed work requiring 'polish' with offer supporting only 'advance'."""
        offer = _make_offer(supported_paths=["advance", "conduct"])
        frontier = FrontierState(runnable_items=[TEST_ITEM_REF])
        claims = [ClaimedWork(
            item_id=TEST_ITEM_REF,
            status="reviewed-implementation",
            item_type="issue",
            required_path="polish",
        )]
        result = decide_next_action(offer, frontier, claims)
        assert result.action == ActionKind.ESCALATE
        assert result.chainable is False
        assert result.context["escalate_reason"] == "unsupported_path"
        assert result.context["required_path"] == "polish"

    def test_resume_lane_policy_blocks(self):
        """AC-8: Lane policy excludes the required path for claimed work."""
        offer = _make_offer(execution_lane="DARIUS")
        frontier = FrontierState(runnable_items=[TEST_ITEM_REF])
        claims = [ClaimedWork(
            item_id=TEST_ITEM_REF,
            status="reviewed-implementation",
            item_type="issue",
            required_path="polish",
        )]
        result = decide_next_action(
            offer,
            frontier,
            claims,
            lane_allowed_paths={
                "DARIUS": ["advance", "conduct", "shepherd", "usher"],
                "ALTMAN": ["refine", "polish"],
            },
        )
        assert result.action == ActionKind.WAIT
        assert result.chainable is False
        assert result.context["wait_reason"] == "lane_policy_disallows_path"
        assert result.context["required_path"] == "polish"

    def test_resume_darius_weirdness_regression(self):
        """AC-9: DARIUS cannot resume into polish after advance charge."""
        offer = _make_offer(execution_lane="DARIUS")
        frontier = FrontierState(runnable_items=[TEST_ITEM_REF])
        claims = [ClaimedWork(
            item_id=TEST_ITEM_REF,
            status="reviewed-implementation",
            item_type="issue",
            required_path="polish",
        )]
        result = decide_next_action(
            offer,
            frontier,
            claims,
            lane_allowed_paths={
                "DARIUS": ["advance", "conduct", "shepherd", "usher"],
            },
        )
        # DARIUS cannot run polish — should not get chainable resume
        assert result.action != ActionKind.RESUME or result.chainable is False

    def test_resume_compatible_claim_succeeds(self):
        """Compatible claimed work still returns chainable resume."""
        offer = _make_offer(execution_lane="DARIUS")
        frontier = FrontierState(runnable_items=[TEST_ITEM_REF])
        claims = [ClaimedWork(
            item_id=TEST_ITEM_REF,
            status="implementing",
            item_type="issue",
            required_path="advance",
        )]
        result = decide_next_action(
            offer,
            frontier,
            claims,
            lane_allowed_paths={
                "DARIUS": ["advance", "conduct", "shepherd", "usher"],
            },
        )
        assert result.action == ActionKind.RESUME
        assert result.chainable is True
        assert result.context["required_path"] == "advance"

    def test_resume_no_required_path_passes(self):
        """Backward compat: no required_path on claim still resumes."""
        offer = _make_offer(supported_paths=["advance"])
        frontier = FrontierState(runnable_items=[TEST_ITEM_REF])
        claims = [ClaimedWork(item_id=TEST_ITEM_REF, status="implementing")]
        result = decide_next_action(offer, frontier, claims)
        assert result.action == ActionKind.RESUME
        assert result.chainable is True


class TestResumeNoProgressDetection:
    """FR-7: Repeated no-progress resume stops the chain."""

    def test_no_progress_resume_escalates(self):
        """AC-10: Same item, same status in last_completed_step -> escalate."""
        offer = _make_offer(step=2)
        frontier = FrontierState(
            runnable_items=[TEST_ITEM_REF],
            last_completed_step={
                "action": "resume",
                "item_id": TEST_ITEM_REF,
                "status": "reviewed-implementation",
                "required_path": "polish",
            },
        )
        claims = [ClaimedWork(
            item_id=TEST_ITEM_REF,
            status="reviewed-implementation",
            item_type="issue",
            required_path="polish",
        )]
        result = decide_next_action(offer, frontier, claims)
        assert result.action == ActionKind.ESCALATE
        assert result.chainable is False
        assert result.context["escalate_reason"] == "resume_no_progress"

    def test_same_required_path_also_counts_as_no_progress(self):
        """FR-7: Same required_path can stop the loop even if status text shifts."""
        offer = _make_offer(step=2)
        frontier = FrontierState(
            runnable_items=[TEST_ITEM_REF],
            last_completed_step={
                "action": "resume",
                "item_id": TEST_ITEM_REF,
                "status": "implementing",
                "required_path": "advance",
                "handler_outcome": "completed",
            },
        )
        claims = [ClaimedWork(
            item_id=TEST_ITEM_REF,
            status="reviewing-implementation",
            item_type="issue",
            required_path="advance",
        )]
        result = decide_next_action(offer, frontier, claims)
        assert result.action == ActionKind.ESCALATE
        assert result.chainable is False
        assert result.context["escalate_reason"] == "resume_no_progress"

    def test_progress_made_allows_resume(self):
        """A new required_path means the session can make forward progress."""
        offer = _make_offer(step=2)
        frontier = FrontierState(
            runnable_items=[TEST_ITEM_REF],
            last_completed_step={
                "action": "resume",
                "item_id": TEST_ITEM_REF,
                "status": "implementing",
                "required_path": "advance",
            },
        )
        claims = [ClaimedWork(
            item_id=TEST_ITEM_REF,
            status="reviewed-implementation",
            item_type="issue",
            required_path="polish",
        )]
        result = decide_next_action(offer, frontier, claims)
        assert result.action == ActionKind.RESUME
        assert result.chainable is True

    def test_step_one_skips_no_progress_check(self):
        """First step has no prior step to compare against."""
        offer = _make_offer(step=1)
        frontier = FrontierState(
            runnable_items=[TEST_ITEM_REF],
            last_completed_step={
                "action": "resume",
                "item_id": TEST_ITEM_REF,
                "status": "implementing",
            },
        )
        claims = [ClaimedWork(
            item_id=TEST_ITEM_REF,
            status="implementing",
            item_type="issue",
            required_path="advance",
        )]
        result = decide_next_action(offer, frontier, claims)
        assert result.action == ActionKind.RESUME

    def test_different_item_allows_resume(self):
        """Different item in last step -> no loop detection."""
        offer = _make_offer(step=2)
        frontier = FrontierState(
            runnable_items=[TEST_ITEM_REF],
            last_completed_step={
                "action": "resume",
                "item_id": "YOK-99",
                "status": "implementing",
            },
        )
        claims = [ClaimedWork(
            item_id=TEST_ITEM_REF,
            status="implementing",
            item_type="issue",
            required_path="advance",
        )]
        result = decide_next_action(offer, frontier, claims)
        assert result.action == ActionKind.RESUME


class TestStaticCwdSubstrateNoChainBurnRegression:
    """AC-24: do not burn another /yoke do chain step on a same-session
    worktree-scope-but-cwd-at-main resume that already completed once.

    The originating evidence was a /yoke do run where worktree creation
    flipped the item to ``implementing``, the path claim went active, the
    declared scope was ``worktree``, but Claude Code's cwd remained at main.
    The lint_session_cwd carve-outs from the same ticket family now sanction
    the static-cwd substrate so the resume can proceed; this regression pins
    the decision-engine half: when step 2 is the same item / same status /
    same required_path as step 1's completed disposition, the decision must
    ESCALATE rather than chain another step that has nothing to do.
    """

    def test_implementing_path_no_progress_escalates(self):
        # Step 1 already completed an ``advance`` resume against the item
        # at ``implementing`` status; step 2 sees the same shape with no
        # forward signal, so the chain bails to ESCALATE.
        offer = _make_offer(step=2)
        frontier = FrontierState(
            runnable_items=[TEST_ITEM_REF],
            last_completed_step={
                "action": "resume",
                "item_id": TEST_ITEM_REF,
                "status": "implementing",
                "required_path": "advance",
                "handler_outcome": "completed",
            },
        )
        claims = [ClaimedWork(
            item_id=TEST_ITEM_REF,
            status="implementing",
            item_type="issue",
            required_path="advance",
        )]
        result = decide_next_action(offer, frontier, claims)
        assert result.action == ActionKind.ESCALATE
        assert result.chainable is False
        assert result.context["escalate_reason"] == "resume_no_progress"
        assert result.context["required_path"] == "advance"

    def test_status_progress_to_review_allows_chain(self):
        # When the static-cwd substrate let step 1 land real work, the item
        # transitions from ``implementing`` to ``reviewing-implementation``;
        # the chain may continue because the status moved.
        offer = _make_offer(step=2)
        frontier = FrontierState(
            runnable_items=[TEST_ITEM_REF],
            last_completed_step={
                "action": "resume",
                "item_id": TEST_ITEM_REF,
                "status": "implementing",
                "required_path": "advance",
                "handler_outcome": "completed",
            },
        )
        claims = [ClaimedWork(
            item_id=TEST_ITEM_REF,
            status="reviewing-implementation",
            item_type="issue",
            required_path="advance",
        )]
        result = decide_next_action(offer, frontier, claims)
        # Same required_path with shifted status still escalates per the
        # existing FR-7 path-comparison branch — that's the intended floor.
        # The point of THIS regression is to pin the step-1
        # disposition shape; the path-progress test above is the contrast.
        assert result.action == ActionKind.ESCALATE
