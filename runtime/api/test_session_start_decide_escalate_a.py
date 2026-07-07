"""decide_next_action — escalate branch (blocker-driven escalate paths)."""

from __future__ import annotations

from yoke_core.domain.session import (
    ActionKind,
    FrontierState,
    decide_next_action,
)
from runtime.api.session_start_test_helpers import (
    test_item_ref as _test_item_ref,
    make_offer as _make_offer,
)


class TestDecideNextActionEscalate:
    """Priority 3: escalate when all items are blocked."""

    def test_escalate_when_all_blocked(self):
        offer = _make_offer()
        frontier = FrontierState(
            runnable_items=[],
            blocked_items=["YOK-20", "YOK-21"],
            sml_coherent=True,
        )
        result = decide_next_action(offer, frontier)
        assert result.action == ActionKind.ESCALATE
        assert result.chainable is False
        assert result.context["blocked_items"] == ["YOK-20", "YOK-21"]
        assert "2" in result.reason
        assert result.correlation_id == "test-session-001"

    def test_escalate_when_blocked_and_incoherent_sml(self):
        """All blocked + incoherent SML -> escalate (blocked takes priority)."""
        offer = _make_offer()
        frontier = FrontierState(
            runnable_items=[],
            blocked_items=["YOK-30"],
            sml_coherent=False,
        )
        result = decide_next_action(offer, frontier)
        assert result.action == ActionKind.ESCALATE

    def test_escalate_includes_lane_filtered_count(self):
        """Escalate context includes lane_filtered_count when items were filtered."""
        offer = _make_offer()
        frontier = FrontierState(
            runnable_items=[],
            blocked_items=["YOK-20"],
            sml_coherent=True,
            lane_filtered_count=5,
        )
        result = decide_next_action(offer, frontier)
        assert result.action == ActionKind.ESCALATE
        assert result.context["lane_filtered_count"] == 5
        assert "lane_filtered_note" in result.context
        assert "5 item(s)" in result.context["lane_filtered_note"]

    def test_escalate_omits_lane_filtered_when_zero(self):
        """Escalate context omits lane_filtered fields when count is zero."""
        offer = _make_offer()
        frontier = FrontierState(
            runnable_items=[],
            blocked_items=["YOK-20"],
            sml_coherent=True,
            lane_filtered_count=0,
        )
        result = decide_next_action(offer, frontier)
        assert result.action == ActionKind.ESCALATE
        assert "lane_filtered_count" not in result.context

    def test_escalate_with_blockers_propagates_lane_filtered_items(self):
        """Blocker-driven escalate also carries structured filtered items."""
        offer = _make_offer()
        filtered_detail = [
            {
                "item_id": _test_item_ref(81),
                "title": "Refine this later",
                "status": "idea",
                "next_step": "refine",
                "required_path": "refine",
                "rank": 0,
                "claim_state": "unclaimed",
            }
        ]
        frontier = FrontierState(
            runnable_items=[],
            blocked_items=[_test_item_ref(20)],
            sml_coherent=True,
            lane_filtered_count=1,
            lane_filtered_items=filtered_detail,
        )
        result = decide_next_action(offer, frontier)
        assert result.action == ActionKind.ESCALATE
        assert result.context["lane_filtered_count"] == 1
        assert result.context["lane_filtered_items"] == filtered_detail
