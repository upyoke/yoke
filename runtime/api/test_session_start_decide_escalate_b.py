"""decide_next_action — filtered-empty WAIT + signal-helper + blocker-precedence coverage."""

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
    """Filtered-empty WAIT paths, blocker precedence, and lane-filtered signal helper."""

    def test_filtered_empty_lane_returns_no_lane_compatible_work_wait(self):
        """AC-5: no runnable, no blockers, lane_filtered>0 -> WAIT with no_lane_compatible_work."""
        offer = _make_offer()
        frontier = FrontierState(
            runnable_items=[],
            blocked_items=[],
            exceptional_items=[],
            sml_coherent=True,
            lane_filtered_count=2,
        )
        result = decide_next_action(offer, frontier)
        assert result.action == ActionKind.WAIT
        assert result.chainable is False
        assert result.context["wait_reason"] == "no_lane_compatible_work"
        assert result.context["lane_filtered_count"] == 2
        assert result.context["lane_filtered_items"] == []
        assert result.context["lane_filtered_paths"] == []
        assert "2 item(s)" in result.context["lane_filtered_note"]
        assert "filtered by lane policy" in result.context["lane_filtered_note"]
        # Must NOT be FEED or ESCALATE — that is the bug this change fixes
        assert result.action != ActionKind.FEED
        assert result.action != ActionKind.ESCALATE

    def test_filtered_empty_wait_includes_structured_filtered_items(self):
        """AC-6: WAIT context carries per-item detail and lane_filtered_paths."""
        offer = _make_offer(execution_lane="ALTMAN")
        filtered_items = [
            {
                "item_id": _test_item_ref(77),
                "title": "Needs advance",
                "status": "refined-idea",
                "next_step": "advance",
                "required_path": "advance",
                "rank": 0,
                "claim_state": "unclaimed",
            },
            {
                "item_id": _test_item_ref(78),
                "title": "Also needs advance",
                "status": "refined-idea",
                "next_step": "advance",
                "required_path": "advance",
                "rank": 1,
                "claim_state": "claimed_by_stale",
            },
        ]
        frontier = FrontierState(
            runnable_items=[],
            blocked_items=[],
            sml_coherent=True,
            lane_filtered_count=2,
            lane_filtered_items=filtered_items,
        )
        result = decide_next_action(offer, frontier)
        assert result.action == ActionKind.WAIT
        assert result.context["wait_reason"] == "no_lane_compatible_work"
        assert result.context["lane_filtered_items"] == filtered_items
        # actual_lane is the offering session's lane
        assert result.context["actual_lane"] == "ALTMAN"
        # lane_filtered_paths is a compact grouped view of (path, count)
        assert result.context["lane_filtered_paths"] == [
            {"required_path": "advance", "count": 2},
        ]

    def test_filtered_empty_wait_not_triggered_when_runnable_exists(self):
        """lane_filtered>0 does not fire if runnable items are present — charge wins."""
        offer = _make_offer()
        frontier = FrontierState(
            runnable_items=[_test_item_ref(99)],
            blocked_items=[],
            sml_coherent=True,
            lane_filtered_count=3,
        )
        result = decide_next_action(offer, frontier)
        assert result.action == ActionKind.CHARGE

    def test_blockers_escalate_wins_over_lane_filtered_wait(self):
        """AC-7: blocker-driven escalate wins when both apply; lane signal rides along."""
        offer = _make_offer()
        frontier = FrontierState(
            runnable_items=[],
            blocked_items=[_test_item_ref(20)],
            sml_coherent=True,
            lane_filtered_count=3,
        )
        result = decide_next_action(offer, frontier)
        # Blocker precedence preserved — still ESCALATE, not WAIT
        assert result.action == ActionKind.ESCALATE
        # no_lane_compatible_work wait_reason must NOT replace blocker reason
        assert result.context.get("wait_reason") != "no_lane_compatible_work"
        # Lane-filtered signal still rides along so the operator sees both
        assert result.context["lane_filtered_count"] == 3

    def test_filtered_empty_wait_not_triggered_when_count_zero(self):
        """lane_filtered_count=0 is the pure-empty case — FEED with no_runnable_items."""
        offer = _make_offer()
        frontier = FrontierState(
            runnable_items=[],
            blocked_items=[],
            sml_coherent=True,
            lane_filtered_count=0,
        )
        result = decide_next_action(offer, frontier)
        assert result.action == ActionKind.FEED
        assert result.context["trigger"] == "no_runnable_items"
        assert "lane_filtered_count" not in result.context

    def test_filtered_empty_wait_not_triggered_when_sml_incoherent(self):
        """Strategize wins over filtered-empty WAIT when SML is incoherent."""
        offer = _make_offer()
        frontier = FrontierState(
            runnable_items=[],
            blocked_items=[],
            sml_coherent=False,
            lane_filtered_count=3,
        )
        result = decide_next_action(offer, frontier)
        assert result.action == ActionKind.STRATEGIZE

    def test_lane_filtered_count_always_accompanied_by_note(self):
        """Any outgoing context with lane_filtered_count must also carry lane_filtered_note.
        This guards against future edits that add a new lane_filtered_count emitter
        without the paired note.
        """
        scenarios = [
            # (description, FrontierState kwargs)
            (
                "escalate-with-blockers + lane_filtered",
                dict(
                    runnable_items=[],
                    blocked_items=[_test_item_ref(20)],
                    sml_coherent=True,
                    lane_filtered_count=3,
                ),
            ),
            (
                "filtered-empty WAIT (no_lane_compatible_work)",
                dict(
                    runnable_items=[],
                    blocked_items=[],
                    sml_coherent=True,
                    lane_filtered_count=5,
                ),
            ),
        ]
        for desc, kwargs in scenarios:
            frontier = FrontierState(**kwargs)
            result = decide_next_action(_make_offer(), frontier)
            ctx = result.context or {}
            if "lane_filtered_count" in ctx:
                assert "lane_filtered_note" in ctx, (
                    f"{desc}: lane_filtered_count present but lane_filtered_note missing"
                )
                assert str(ctx["lane_filtered_count"]) in ctx["lane_filtered_note"], (
                    f"{desc}: note does not cite the count"
                )

    def test_apply_lane_filtered_signal_helper_attaches_to_any_context(self):
        """AC-3: the _apply_lane_filtered_signal helper is the single source
        of truth for lane-filtered context keys. Any branch that uses it
        gets identical signal attachment — this protects AC-3 even if
        future code paths reintroduce FEED on a lane-filtered frontier."""
        from yoke_core.domain.session import _apply_lane_filtered_signal

        filtered = [
            {
                "item_id": _test_item_ref(9001),
                "title": "Test",
                "status": "idea",
                "next_step": "refine",
                "required_path": "refine",
                "rank": 0,
                "claim_state": "unclaimed",
            }
        ]
        frontier = FrontierState(
            runnable_items=[],
            blocked_items=[],
            sml_coherent=True,
            lane_filtered_count=1,
            lane_filtered_items=filtered,
        )
        # Simulate a FEED context that needs to gain the signal
        ctx: dict = {"trigger": "no_runnable_items", "blocked_count": 0}
        result = _apply_lane_filtered_signal(ctx, frontier)
        # Returns the same dict (mutated in place)
        assert result is ctx
        # All three keys attached
        assert ctx["lane_filtered_count"] == 1
        assert "lane_filtered_note" in ctx
        assert ctx["lane_filtered_items"] == filtered
        # Pre-existing trigger key is preserved
        assert ctx["trigger"] == "no_runnable_items"

    def test_apply_lane_filtered_signal_no_op_when_count_zero(self):
        """The helper must not pollute context when no filtering occurred."""
        from yoke_core.domain.session import _apply_lane_filtered_signal

        frontier = FrontierState(
            runnable_items=[],
            blocked_items=[],
            sml_coherent=True,
            lane_filtered_count=0,
        )
        ctx = {"trigger": "no_runnable_items"}
        _apply_lane_filtered_signal(ctx, frontier)
        assert "lane_filtered_count" not in ctx
        assert "lane_filtered_note" not in ctx
        assert "lane_filtered_items" not in ctx

    def test_lane_filtered_items_round_trip_through_decision_engine(self):
        """AC-6: structured filtered-item detail is preserved from
        FrontierState input through NextAction.context output, unchanged."""
        offer = _make_offer()
        filtered = [
            {
                "item_id": _test_item_ref(9101),
                "title": "A",
                "status": "idea",
                "next_step": "refine",
                "required_path": "refine",
                "rank": 0,
                "claim_state": "unclaimed",
            },
            {
                "item_id": _test_item_ref(9102),
                "title": "B",
                "status": "refining-idea",
                "next_step": "refine",
                "required_path": "refine",
                "rank": 1,
                "claim_state": "unclaimed",
            },
        ]
        frontier = FrontierState(
            runnable_items=[],
            blocked_items=[],
            sml_coherent=True,
            lane_filtered_count=len(filtered),
            lane_filtered_items=filtered,
        )
        result = decide_next_action(offer, frontier)
        assert result.action == ActionKind.WAIT
        assert result.context["wait_reason"] == "no_lane_compatible_work"
        assert result.context["lane_filtered_items"] == filtered
        # AC-6 enumerates: item_id, title, status, next_step/required_path,
        # rank, claim_state. Assert every field survives.
        for item in result.context["lane_filtered_items"]:
            for key in (
                "item_id", "title", "status", "next_step", "required_path",
                "rank", "claim_state",
            ):
                assert key in item, f"filtered item missing key: {key}"
