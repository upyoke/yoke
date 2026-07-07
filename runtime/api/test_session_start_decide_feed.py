"""decide_next_action — feed branch (drift_review and no-runnable-items triggers)."""

from __future__ import annotations

from yoke_core.domain.session import (
    ActionKind,
    FrontierState,
    decide_next_action,
)
from runtime.api.session_start_test_helpers import make_offer as _make_offer


class TestDecideNextActionFeed:
    """Priority 3b/4: feed when drift_review=frontier_only or no runnable items, SML is coherent."""

    def test_feed_when_no_runnable_but_coherent(self):
        offer = _make_offer()
        frontier = FrontierState(
            runnable_items=[],
            sml_coherent=True,
        )
        result = decide_next_action(offer, frontier)
        assert result.action == ActionKind.FEED
        assert result.chainable is False

    def test_feed_includes_blocked_count(self):
        """Feed fires when frontier is truly empty (no blocked, no runnable)."""
        offer = _make_offer()
        frontier = FrontierState(
            runnable_items=[],
            blocked_items=[],
            sml_coherent=True,
        )
        result = decide_next_action(offer, frontier)
        assert result.action == ActionKind.FEED
        assert result.context["blocked_count"] == 0

    def test_feed_no_runnable_includes_trigger_no_runnable_items(self):
        """The no-items feed trigger includes trigger=no_runnable_items."""
        offer = _make_offer()
        frontier = FrontierState(
            runnable_items=[],
            blocked_items=[],
            sml_coherent=True,
        )
        result = decide_next_action(offer, frontier)
        assert result.action == ActionKind.FEED
        assert result.context["trigger"] == "no_runnable_items"

    def test_drift_review_frontier_only_triggers_feed_when_no_selected_item(self):
        """drift_review classification=frontier_only with no selected_item -> feed."""
        offer = _make_offer()
        frontier = FrontierState(
            runnable_items=["YOK-1"],
            selected_item=None,
            scheduler_context={},
            sml_coherent=True,
            drift_review={"classification": "frontier_only", "summary": "test", "checkpoint_start": "", "reviewed_through": "", "delivered_items": []},
        )
        result = decide_next_action(offer, frontier)
        assert result.action == ActionKind.FEED

    def test_drift_review_frontier_only_charge_wins_when_selected_item(self):
        """drift_review=frontier_only but selected_item set -> charge wins."""
        offer = _make_offer()
        frontier = FrontierState(
            runnable_items=["YOK-1"],
            selected_item="YOK-1",
            sml_coherent=True,
            drift_review={"classification": "frontier_only", "summary": "test", "checkpoint_start": "", "reviewed_through": "", "delivered_items": []},
        )
        result = decide_next_action(offer, frontier)
        assert result.action == ActionKind.CHARGE

    def test_drift_review_present_escalate_wins_when_all_blocked(self):
        """drift_review present but all items blocked -> escalate wins."""
        offer = _make_offer()
        frontier = FrontierState(
            runnable_items=[],
            blocked_items=["YOK-5"],
            sml_coherent=True,
            drift_review={"classification": "frontier_only", "summary": "test", "checkpoint_start": "", "reviewed_through": "", "delivered_items": []},
        )
        result = decide_next_action(offer, frontier)
        assert result.action == ActionKind.ESCALATE

    def test_drift_review_frontier_only_no_runnable_no_blockers_triggers_feed(self):
        """drift_review=frontier_only, no runnable, no blockers -> feed."""
        offer = _make_offer()
        frontier = FrontierState(
            runnable_items=[],
            blocked_items=[],
            sml_coherent=True,
            drift_review={"classification": "frontier_only", "summary": "test", "checkpoint_start": "", "reviewed_through": "", "delivered_items": []},
        )
        result = decide_next_action(offer, frontier)
        assert result.action == ActionKind.FEED

    def test_no_drift_review_no_runnable_triggers_no_runnable_items_feed(self):
        """No drift_review, no runnable -> no_runnable_items feed."""
        offer = _make_offer()
        frontier = FrontierState(
            runnable_items=[],
            blocked_items=[],
            sml_coherent=True,
        )
        result = decide_next_action(offer, frontier)
        assert result.action == ActionKind.FEED
        assert result.context["trigger"] == "no_runnable_items"

    def test_filtered_empty_wait_preempts_drift_review_feed(self):
        """AC-8: filtered-empty WAIT fires before drift_review FEED — operator
        must be told that existing work is not compatible with this lane instead of
        silently auto-feeding."""
        offer = _make_offer()
        frontier = FrontierState(
            runnable_items=[],
            blocked_items=[],
            sml_coherent=True,
            lane_filtered_count=2,
            drift_review={
                "classification": "frontier_only",
                "summary": "test",
                "checkpoint_start": "",
                "reviewed_through": "",
                "delivered_items": [],
            },
        )
        result = decide_next_action(offer, frontier)
        # WAIT (no_lane_compatible_work) wins over drift_review FEED
        assert result.action == ActionKind.WAIT
        assert result.context["wait_reason"] == "no_lane_compatible_work"

    def test_drift_review_feed_omits_lane_filtered_when_count_zero(self):
        """Zero-count drift-review FEED preserves the existing compact context."""
        offer = _make_offer()
        frontier = FrontierState(
            runnable_items=[],
            blocked_items=[],
            sml_coherent=True,
            lane_filtered_count=0,
            drift_review={
                "classification": "frontier_only",
                "summary": "delivered work impacts frontier",
                "checkpoint_start": "",
                "reviewed_through": "",
                "delivered_items": [],
            },
        )
        result = decide_next_action(offer, frontier)
        assert result.action == ActionKind.FEED
        assert result.context["trigger"] == "drift_review"
        assert "lane_filtered_count" not in result.context  # zero-count: omitted
