"""Tests for yoke_core.domain.session — drift-review routing/checkpointing,
path derivation mapping, and path-support validation."""

from __future__ import annotations

import os
import sys
from runtime.api.test_constants import TEST_MODEL_ID

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from yoke_core.domain.session import (
    ActionKind,
    FrontierState,
    NextAction,
    SessionOffer,
    _NEXT_STEP_TO_PATH,
    build_drift_review_failure_action,
    decide_next_action,
    should_emit_drift_review_checkpoint,
)


def _make_offer(**overrides):
    """Helper to create a SessionOffer with sensible defaults."""
    defaults = {
        "session_id": "test-session-001",
        "executor": "DARIUS",
        "provider": "anthropic",
        "model": TEST_MODEL_ID,
        "workspace": "/tmp/yoke",
    }
    defaults.update(overrides)
    return SessionOffer(**defaults)


class TestDriftReviewRouting:
    """drift_review-based routing in decide_next_action."""

    def test_drift_review_sml_only_triggers_strategize(self):
        """drift_review classification=sml_only -> strategize."""
        frontier = FrontierState(
            sml_coherent=True,
            drift_review={"classification": "sml_only", "summary": "test", "checkpoint_start": "", "reviewed_through": "", "delivered_items": []},
        )
        result = decide_next_action(_make_offer(), frontier)
        assert result.action == ActionKind.STRATEGIZE

    def test_drift_review_both_triggers_strategize_with_follow_on(self):
        """drift_review classification=both -> strategize with follow_on=feed."""
        frontier = FrontierState(
            sml_coherent=True,
            drift_review={"classification": "both", "summary": "test", "checkpoint_start": "", "reviewed_through": "", "delivered_items": []},
        )
        result = decide_next_action(_make_offer(), frontier)
        assert result.action == ActionKind.STRATEGIZE
        assert result.context.get("follow_on") == "feed"

    def test_drift_review_neither_falls_through(self):
        """drift_review classification=neither -> falls through to normal flow."""
        frontier = FrontierState(
            sml_coherent=True,
            runnable_items=["YOK-1"],
            selected_item="YOK-1",
            drift_review={"classification": "neither", "summary": "test", "checkpoint_start": "", "reviewed_through": "", "delivered_items": []},
            scheduler_context={"next_step": "conduct", "item_type": "issue", "status": "refined-idea", "title": "t", "rank": 0, "explanation": "", "adapter": ""},
        )
        result = decide_next_action(_make_offer(), frontier)
        assert result.action == ActionKind.CHARGE


class TestDriftReviewCheckpointing:
    """checkpoint emission follows the chosen follow-on action."""

    def test_neither_checkpoints_immediately(self):
        result = NextAction(
            action=ActionKind.CHARGE,
            reason="charge",
            chainable=True,
            correlation_id="sess-1",
        )
        drift = {"classification": "neither"}
        assert should_emit_drift_review_checkpoint(result, drift) is True

    def test_frontier_only_checkpoints_only_for_drift_review_feed(self):
        result = NextAction(
            action=ActionKind.FEED,
            reason="feed",
            chainable=False,
            correlation_id="sess-1",
            context={"trigger": "drift_review"},
        )
        drift = {"classification": "frontier_only"}
        assert should_emit_drift_review_checkpoint(result, drift) is True

    def test_frontier_only_does_not_checkpoint_when_charge_wins(self):
        result = NextAction(
            action=ActionKind.CHARGE,
            reason="charge",
            chainable=True,
            correlation_id="sess-1",
        )
        drift = {"classification": "frontier_only"}
        assert should_emit_drift_review_checkpoint(result, drift) is False

    def test_sml_driven_reviews_wait_for_strategize_checkpoint(self):
        result = NextAction(
            action=ActionKind.STRATEGIZE,
            reason="strategize",
            chainable=False,
            correlation_id="sess-1",
            context={"trigger": "drift_review"},
        )
        assert should_emit_drift_review_checkpoint(result, {"classification": "sml_only"}) is False
        assert should_emit_drift_review_checkpoint(result, {"classification": "both"}) is False

    def test_frontier_only_checkpoints_for_suppressed_wait_with_drift_review_trigger(self):
        # When the process-offer gate suppresses a drift-originated
        # FEED into a non-terminal WAIT, the drift cursor must still
        # advance — otherwise drift re-triggers forever on every offer.
        # The predicate reads original_context.trigger inside the
        # suppressed_process_recommendation payload.
        result = NextAction(
            action=ActionKind.WAIT,
            reason="FEED suppressed by do_process_offer_feed=false",
            chainable=False,
            correlation_id="sess-1",
            context={
                "wait_reason": "process_suppressed_no_alternative",
                "suppressed_process_recommendation": {
                    "process_key": "FEED",
                    "config_key": "do_process_offer_feed",
                    "recommended_action": "feed",
                    "direct_command": "/yoke feed",
                    "skip_reason": "process_disabled_by_config",
                    "original_reason": "Drift review: frontier impacted.",
                    "original_context": {"trigger": "drift_review"},
                },
            },
        )
        drift = {"classification": "frontier_only"}
        assert should_emit_drift_review_checkpoint(result, drift) is True

    def test_frontier_only_does_not_checkpoint_for_unrelated_wait(self):
        # Defense against confusing the new branch with arbitrary WAITs.
        # A WAIT whose suppressed_process_recommendation does NOT carry
        # original_context.trigger='drift_review' (or any other WAIT
        # shape) must not advance the drift cursor.
        no_trigger = NextAction(
            action=ActionKind.WAIT,
            reason="no work",
            chainable=False,
            correlation_id="sess-1",
            context={"wait_reason": "no_runnable_items"},
        )
        suppressed_non_drift = NextAction(
            action=ActionKind.WAIT,
            reason="FEED suppressed (non-drift origin)",
            chainable=False,
            correlation_id="sess-1",
            context={
                "wait_reason": "process_suppressed_no_alternative",
                "suppressed_process_recommendation": {
                    "process_key": "FEED",
                    "original_context": {"trigger": "no_runnable"},
                },
            },
        )
        drift = {"classification": "frontier_only"}
        assert should_emit_drift_review_checkpoint(no_trigger, drift) is False
        assert should_emit_drift_review_checkpoint(suppressed_non_drift, drift) is False

    def test_drift_review_failure_builds_escalate(self):
        result = build_drift_review_failure_action("sess-1", "boom")
        assert result.action == ActionKind.ESCALATE
        assert result.chainable is False
        assert result.context["trigger"] == "drift_review"
        assert result.context["error"] == "boom"


class TestPathDerivationMapping:
    """Verify _NEXT_STEP_TO_PATH maps all scheduler next_step values."""

    def test_refine_maps_to_refine(self):
        assert _NEXT_STEP_TO_PATH["refine"] == "refine"

    def test_shepherd_maps_to_shepherd(self):
        assert _NEXT_STEP_TO_PATH["shepherd"] == "shepherd"

    def test_conduct_maps_to_conduct(self):
        assert _NEXT_STEP_TO_PATH["conduct"] == "conduct"

    def test_advance_maps_to_advance(self):
        assert _NEXT_STEP_TO_PATH["advance"] == "advance"

    def test_polish_maps_to_polish(self):
        assert _NEXT_STEP_TO_PATH["polish"] == "polish"

    def test_usher_maps_to_usher(self):
        assert _NEXT_STEP_TO_PATH["usher"] == "usher"

    def test_all_six_paths_mapped(self):
        assert set(_NEXT_STEP_TO_PATH.values()) == {"refine", "shepherd", "conduct", "advance", "polish", "usher"}

    def test_advance_active_no_longer_exists(self):
        """AC-1/AC-9: advance-active is fully removed from path mapping."""
        assert "advance-active" not in _NEXT_STEP_TO_PATH


class TestPathSupportValidation:
    """AC-2: decide_next_action returns escalate with unsupported_path when
    non-empty supported_paths excludes the required downstream path.
    Empty supported_paths means all paths supported."""

    def _frontier_with_next_step(self, next_step: str) -> FrontierState:
        """Create a FrontierState with a selected item and scheduler context."""
        return FrontierState(
            runnable_items=["YOK-10"],
            sml_coherent=True,
            selected_item="YOK-10",
            scheduler_context={
                "next_step": next_step,
                "item_type": "issue",
                "status": "ready",
                "title": "Test item",
                "rank": 1,
                "explanation": "test",
                "adapter": "claude-code",
            },
        )

    def test_escalate_when_path_not_supported(self):
        """AC-2: shepherd required but only advance supported -> escalate."""
        offer = _make_offer(supported_paths=["advance"])
        frontier = self._frontier_with_next_step("shepherd")
        result = decide_next_action(offer, frontier)
        assert result.action == ActionKind.ESCALATE
        assert result.context["escalate_reason"] == "unsupported_path"
        assert result.context["required_path"] == "shepherd"
        assert result.context["supported_paths"] == ["advance"]

    def test_charge_when_path_is_supported(self):
        offer = _make_offer(supported_paths=["shepherd", "advance"])
        frontier = self._frontier_with_next_step("shepherd")
        result = decide_next_action(offer, frontier)
        assert result.action == ActionKind.CHARGE

    def test_backward_compat_empty_supported_paths(self):
        """AC-3: Empty list means all paths supported."""
        offer = _make_offer(supported_paths=[])
        frontier = self._frontier_with_next_step("shepherd")
        result = decide_next_action(offer, frontier)
        assert result.action == ActionKind.CHARGE

    def test_backward_compat_no_supported_paths(self):
        """AC-3: No supported_paths field (default) means all supported."""
        offer = _make_offer()
        frontier = self._frontier_with_next_step("conduct")
        result = decide_next_action(offer, frontier)
        assert result.action == ActionKind.CHARGE

    def test_escalate_conduct_not_in_supported(self):
        offer = _make_offer(supported_paths=["shepherd"])
        frontier = self._frontier_with_next_step("conduct")
        result = decide_next_action(offer, frontier)
        assert result.action == ActionKind.ESCALATE
        assert result.context["required_path"] == "conduct"

    def test_escalate_refine_not_in_supported(self):
        """refine required but not supported -> escalate."""
        offer = _make_offer(supported_paths=["usher"])
        frontier = self._frontier_with_next_step("refine")
        result = decide_next_action(offer, frontier)
        assert result.action == ActionKind.ESCALATE
        assert result.context["required_path"] == "refine"

    def test_escalate_polish_not_in_supported(self):
        """polish required but not supported -> escalate."""
        offer = _make_offer(supported_paths=["conduct"])
        frontier = self._frontier_with_next_step("polish")
        result = decide_next_action(offer, frontier)
        assert result.action == ActionKind.ESCALATE
        assert result.context["required_path"] == "polish"

    def test_escalate_usher_not_in_supported(self):
        offer = _make_offer(supported_paths=["refine", "conduct"])
        frontier = self._frontier_with_next_step("usher")
        result = decide_next_action(offer, frontier)
        assert result.action == ActionKind.ESCALATE
        assert result.context["required_path"] == "usher"

    def test_escalate_not_chainable(self):
        offer = _make_offer(supported_paths=["refine"])
        frontier = self._frontier_with_next_step("shepherd")
        result = decide_next_action(offer, frontier)
        assert result.chainable is False

    def test_escalate_includes_selected_item(self):
        offer = _make_offer(supported_paths=["refine"])
        frontier = self._frontier_with_next_step("shepherd")
        result = decide_next_action(offer, frontier)
        assert result.context["selected_item"] == "YOK-10"

    def test_no_escalate_when_scheduler_context_missing(self):
        """Legacy path: no scheduler context means no path validation."""
        offer = _make_offer(supported_paths=["refine"])
        frontier = FrontierState(
            runnable_items=["YOK-10"],
            sml_coherent=True,
            selected_item="YOK-10",
            scheduler_context=None,
        )
        # Should fall through to charge (legacy fallback doesn't use scheduler_context)
        # Actually with selected_item set but no scheduler_context, it still charges
        # because the first charge branch checks selected_item + sml_coherent
        # but supported_paths check requires scheduler_context
        result = decide_next_action(offer, frontier)
        assert result.action == ActionKind.CHARGE
