"""decide_next_action — resume, charge, strategize, wait, and wait-path branches."""

from __future__ import annotations

from yoke_core.domain.session import (
    ActionKind,
    ClaimedWork,
    FrontierState,
    NextAction,
    decide_next_action,
)
from runtime.api.session_start_test_helpers import (
    TEST_ITEM_REF,
    make_offer as _make_offer,
)


# ---------------------------------------------------------------------------
# decide_next_action — resume / charge / strategize / wait
# ---------------------------------------------------------------------------


class TestDecideNextActionResume:
    """Priority 1: resume when session has active claims."""

    def test_resume_with_item_claim(self):
        offer = _make_offer()
        frontier = FrontierState(runnable_items=["YOK-10"])
        claims = [ClaimedWork(item_id=TEST_ITEM_REF, status="active")]
        result = decide_next_action(offer, frontier, claims)
        assert result.action == ActionKind.RESUME
        assert result.chainable is True
        assert result.context["item_id"] == TEST_ITEM_REF
        assert result.correlation_id == "test-session-001"

    def test_resume_with_epic_task_claim(self):
        offer = _make_offer()
        frontier = FrontierState()
        # epic task status uses implementing, not legacy active
        claims = [ClaimedWork(epic_id=100, task_num=3, status="implementing")]
        result = decide_next_action(offer, frontier, claims)
        assert result.action == ActionKind.RESUME
        assert result.context["epic_id"] == 100
        assert result.context["task_num"] == 3

    def test_resume_takes_priority_over_charge(self):
        """Even with runnable items, claimed work wins."""
        offer = _make_offer()
        frontier = FrontierState(runnable_items=["YOK-10", "YOK-11"])
        claims = [ClaimedWork(item_id=TEST_ITEM_REF, status="active")]
        result = decide_next_action(offer, frontier, claims)
        assert result.action == ActionKind.RESUME


class TestDecideNextActionCharge:
    """Priority 2: charge when runnable items exist and SML is coherent."""

    def test_charge_with_runnable_items(self):
        offer = _make_offer()
        frontier = FrontierState(
            runnable_items=["YOK-10", "YOK-11"],
            sml_coherent=True,
        )
        result = decide_next_action(offer, frontier)
        assert result.action == ActionKind.CHARGE
        assert result.chainable is True
        assert "YOK-10" in result.context["runnable_items"]

    def test_charge_reason_includes_count(self):
        offer = _make_offer()
        frontier = FrontierState(runnable_items=["YOK-10", "YOK-11", "YOK-12"])
        result = decide_next_action(offer, frontier)
        assert "3" in result.reason

    def test_charge_prefers_scheduler_selected_item(self):
        offer = _make_offer()
        frontier = FrontierState(
            runnable_items=["YOK-10", "YOK-11"],
            sml_coherent=True,
            selected_item="YOK-11",
            scheduler_context={},
        )
        result = decide_next_action(offer, frontier)
        assert result.action == ActionKind.CHARGE
        assert result.context["selected_item"] == "YOK-11"


class TestDecideNextActionStrategize:
    """Priority 4: strategize when SML is absent or incoherent."""

    def test_strategize_when_sml_not_coherent(self):
        offer = _make_offer()
        frontier = FrontierState(sml_coherent=False)
        result = decide_next_action(offer, frontier)
        assert result.action == ActionKind.STRATEGIZE
        assert result.chainable is False
        assert "incoherent" in result.reason.lower() or "absent" in result.reason.lower()

    def test_strategize_when_sml_not_coherent_no_runnable(self):
        """sml_coherent=False is the only hard SML check -> strategize."""
        offer = _make_offer()
        frontier = FrontierState(sml_coherent=False, runnable_items=[])
        result = decide_next_action(offer, frontier)
        assert result.action == ActionKind.STRATEGIZE

    def test_strategize_context_includes_sml_coherent(self):
        offer = _make_offer()
        frontier = FrontierState(sml_coherent=False)
        result = decide_next_action(offer, frontier)
        assert result.action == ActionKind.STRATEGIZE
        assert result.context["sml_coherent"] is False

    def test_strategize_with_runnable_but_incoherent_sml(self):
        """Runnable items exist but SML is broken — strategize wins over charge."""
        offer = _make_offer()
        frontier = FrontierState(
            runnable_items=["YOK-10"],
            sml_coherent=False,
        )
        result = decide_next_action(offer, frontier)
        assert result.action == ActionKind.STRATEGIZE


class TestDecideNextActionWait:
    """Priority 6: wait when nothing actionable."""

    def test_wait_when_empty_frontier_coherent(self):
        """Empty frontier with coherent SML -> feed (materialize more)."""
        offer = _make_offer()
        frontier = FrontierState(
            runnable_items=[],
            blocked_items=[],
            sml_coherent=True,
        )
        result = decide_next_action(offer, frontier)
        # Empty frontier + coherent SML -> feed (not wait)
        assert result.action == ActionKind.FEED

    def test_wait_when_scheduler_reports_no_assignable_selection(self):
        """A visible frontier without an assignable step should not re-charge."""
        offer = _make_offer()
        frontier = FrontierState(
            runnable_items=["YOK-10"],
            blocked_items=["YOK-12"],
            sml_coherent=True,
            selected_item=None,
            scheduler_context={},
        )
        result = decide_next_action(offer, frontier)
        assert result.action == ActionKind.WAIT


# ---------------------------------------------------------------------------
# decide_next_action — wait path (defensive fallback)
# ---------------------------------------------------------------------------


class TestDecideNextActionWaitPath:
    """The wait action is a defensive fallback in the decision engine.

    With the current branch structure, the wait path is only reachable via
    direct NextAction construction — all logical branches are covered by
    resume, charge, escalate, feed, and strategize before reaching wait.
    These tests verify the wait directive works correctly when constructed.
    """

    def test_wait_action_direct_construction(self):
        """Wait NextAction can be directly constructed with correct semantics."""
        na = NextAction(
            action=ActionKind.WAIT,
            reason="No actionable work.",
            correlation_id="s1",
        )
        assert na.action == ActionKind.WAIT
        assert na.chainable is False
        assert na.kind == ActionKind.WAIT

    def test_wait_with_context(self):
        """Wait can carry retry-hint context."""
        na = NextAction(
            action=ActionKind.WAIT,
            reason="Nothing to do.",
            correlation_id="s1",
            context={"wait_seconds": 60, "retry_hint": "poll again after cooldown"},
        )
        assert na.context["wait_seconds"] == 60

    def test_wait_not_in_chainable_set(self):
        """Wait is NOT in the _CHAINABLE_ACTIONS set."""
        from yoke_core.domain.session import _CHAINABLE_ACTIONS
        assert ActionKind.WAIT not in _CHAINABLE_ACTIONS
