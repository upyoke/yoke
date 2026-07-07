"""decide_next_action — chainability, purity invariants, and edge-case coverage."""

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


class TestDecideNextActionChainability:
    """AC-5: chainable is True only for resume and charge."""

    def test_resume_is_chainable(self):
        offer = _make_offer()
        claims = [ClaimedWork(item_id=TEST_ITEM_REF)]
        result = decide_next_action(offer, FrontierState(), claims)
        assert result.chainable is True

    def test_charge_is_chainable(self):
        offer = _make_offer()
        frontier = FrontierState(runnable_items=["YOK-10"])
        result = decide_next_action(offer, frontier)
        assert result.chainable is True

    def test_feed_not_chainable(self):
        offer = _make_offer()
        frontier = FrontierState(sml_coherent=True)
        result = decide_next_action(offer, frontier)
        assert result.action == ActionKind.FEED
        assert result.chainable is False

    def test_strategize_not_chainable(self):
        offer = _make_offer()
        frontier = FrontierState(sml_coherent=False)
        result = decide_next_action(offer, frontier)
        assert result.action == ActionKind.STRATEGIZE
        assert result.chainable is False

    def test_wait_not_chainable(self):
        """Wait is the absolute fallback — construct via NextAction directly."""
        na = NextAction(
            action=ActionKind.WAIT,
            reason="No actionable work.",
            correlation_id="s1",
        )
        assert na.chainable is False


class TestDecideNextActionPurity:
    """AC-6: Module has no DB access, no file I/O, no side effects."""

    def test_no_import_of_sqlite3(self):
        import yoke_core.domain.session as mod
        import inspect
        source = inspect.getsource(mod)
        # The decision engine section should not import sqlite3
        # (the module-level imports don't include it)
        assert "import sqlite3" not in source

    def test_no_import_of_subprocess(self):
        import yoke_core.domain.session as mod
        import inspect
        source = inspect.getsource(mod)
        assert "import subprocess" not in source

    def test_no_import_of_os(self):
        import yoke_core.domain.session as mod
        import inspect
        source = inspect.getsource(mod)
        # os is not needed for pure logic
        assert "import os" not in source

    def test_decide_returns_next_action(self):
        offer = _make_offer()
        result = decide_next_action(offer, FrontierState())
        assert isinstance(result, NextAction)

    def test_decide_correlation_id_matches_offer(self):
        offer = _make_offer(session_id="unique-test-id")
        result = decide_next_action(offer, FrontierState())
        assert result.correlation_id == "unique-test-id"


class TestDecideNextActionEdgeCases:
    """Edge cases and priority ordering verification."""

    def test_empty_claims_list_treated_as_no_claims(self):
        offer = _make_offer()
        frontier = FrontierState(runnable_items=["YOK-10"])
        result = decide_next_action(offer, frontier, active_claims=[])
        assert result.action == ActionKind.CHARGE

    def test_none_claims_treated_as_no_claims(self):
        offer = _make_offer()
        frontier = FrontierState(runnable_items=["YOK-10"])
        result = decide_next_action(offer, frontier, active_claims=None)
        assert result.action == ActionKind.CHARGE

    def test_multiple_claims_uses_first(self):
        offer = _make_offer()
        claims = [
            ClaimedWork(item_id=TEST_ITEM_REF, status="active"),
            ClaimedWork(item_id="YOK-43", status="review"),
        ]
        result = decide_next_action(offer, FrontierState(), claims)
        assert result.action == ActionKind.RESUME
        assert result.context["item_id"] == TEST_ITEM_REF

    def test_incoherent_sml_with_runnable_items_strategizes(self):
        """Incoherent SML takes priority: even with runnable items, strategize."""
        offer = _make_offer()
        frontier = FrontierState(
            runnable_items=["YOK-10"],
            sml_coherent=False,
        )
        result = decide_next_action(offer, frontier)
        assert result.action == ActionKind.STRATEGIZE

    def test_single_runnable_item(self):
        """Single-item frontier still charges."""
        offer = _make_offer()
        frontier = FrontierState(runnable_items=["YOK-99"])
        result = decide_next_action(offer, frontier)
        assert result.action == ActionKind.CHARGE
        assert result.context["runnable_items"] == ["YOK-99"]

    def test_claim_with_only_status_field(self):
        """Claims that only have status (no item_id/epic_id) still trigger resume."""
        offer = _make_offer()
        claims = [ClaimedWork(status="active")]
        result = decide_next_action(offer, FrontierState(), claims)
        assert result.action == ActionKind.RESUME
