"""ChainBudgetUnused emission and terminal-reason classification regressions.

Sibling of :mod:`runtime.api.test_do_loop_offer_revalidation`. Keeps the
revalidation/skip-memory regressions there small and the AC-7 / AC-12
terminal-reason coverage isolated. The helpers under test here operate on
plain dicts and do not need the items-schema fixture, so the file has no
DB setup of its own.
"""

from __future__ import annotations

from unittest.mock import patch

from yoke_core.domain.sessions_offer_revalidation import (
    classify_terminal_reason,
    emit_chain_budget_unused_if_remaining,
)


def _sun(item_id: int) -> str:
    return f"YOK-{item_id}"


class TestClassifyTerminalReason:
    """AC-7 / AC-12: classify the terminal reason from this-step skip entries."""

    def test_empty_returns_no_candidates(self):
        assert classify_terminal_reason([]) == "no_candidates"

    def test_all_stale_returns_all_candidates_stale(self):
        entries = [
            {"item_id": _sun(1), "skip_reason": "stale_lifecycle"},
            {"item_id": _sun(2), "skip_reason": "stale_lifecycle"},
        ]
        assert classify_terminal_reason(entries) == "all_candidates_stale"

    def test_all_live_claim_returns_all_candidates_blocked(self):
        entries = [
            {"item_id": _sun(1), "skip_reason": "live_claim_conflict"},
            {"item_id": _sun(2), "skip_reason": "live_claim_conflict"},
        ]
        assert classify_terminal_reason(entries) == "all_candidates_blocked"

    def test_all_disabled_process_returns_all_candidates_disabled_process(self):
        entries = [
            {"process_key": "STRATEGIZE", "skip_reason": "process_disabled_by_config"},
        ]
        assert (
            classify_terminal_reason(entries)
            == "all_candidates_disabled_process"
        )

    def test_all_recoverable_substrate_returns_dedicated_terminal(self):
        entries = [
            {"item_id": _sun(1), "skip_reason": "recoverable_substrate"},
        ]
        assert (
            classify_terminal_reason(entries)
            == "all_candidates_recoverable_substrate"
        )

    def test_mixed_returns_mixed_unavailable(self):
        entries = [
            {"item_id": _sun(1), "skip_reason": "stale_lifecycle"},
            {"item_id": _sun(2), "skip_reason": "live_claim_conflict"},
        ]
        assert classify_terminal_reason(entries) == "mixed_unavailable"

    def test_unknown_skip_reason_falls_back_to_mixed(self):
        entries = [
            {"item_id": _sun(1), "skip_reason": "future_reason_we_have_not_seen"},
        ]
        assert classify_terminal_reason(entries) == "mixed_unavailable"


class TestEmitChainBudgetUnusedIfRemaining:
    """AC-12: emit ChainBudgetUnused on a non-chainable offer with budget left."""

    def _capture_events(self):
        captured: list[dict] = []
        return captured, patch(
            "yoke_core.domain.events.emit_event",
            side_effect=lambda name, **kw: captured.append({"name": name, **kw}),
        )

    def test_emits_when_budget_remaining_and_skips_present(self):
        skip_memory = [
            {
                "item_id": _sun(1),
                "skip_reason": "stale_lifecycle",
                "chain_step": 1,
                "expected_status": "polishing-implementation",
                "current_status": "implemented",
            },
            {
                "item_id": _sun(2),
                "skip_reason": "stale_lifecycle",
                "chain_step": 1,
                "expected_status": "implementing",
                "current_status": "reviewed-implementation",
            },
        ]
        captured, ctx_mgr = self._capture_events()
        with ctx_mgr:
            terminal_reason = emit_chain_budget_unused_if_remaining(
                session_id="budget-keep",
                chain_step=1,
                max_chain_steps=3,
                skip_memory=skip_memory,
                project="yoke",
            )
        assert terminal_reason == "all_candidates_stale"
        events = [c for c in captured if c["name"] == "ChainBudgetUnused"]
        assert len(events) == 1
        ctx = events[0]["context"]
        assert ctx["session_id"] == "budget-keep"
        assert ctx["step"] == 1
        assert ctx["max_chain_steps"] == 3
        assert ctx["remaining_budget"] == 2
        assert ctx["terminal_reason"] == "all_candidates_stale"
        trail = ctx["candidate_trail"]
        assert len(trail) == 2
        assert {entry["item_id"] for entry in trail} == {_sun(1), _sun(2)}
        assert all(
            entry["skip_reason"] == "stale_lifecycle" for entry in trail
        )
        assert trail[0]["expected_status"] == "polishing-implementation"
        assert trail[0]["current_status"] == "implemented"

    def test_does_not_emit_when_budget_exhausted(self):
        skip_memory = [
            {"item_id": _sun(1), "skip_reason": "stale_lifecycle", "chain_step": 3},
        ]
        captured, ctx_mgr = self._capture_events()
        with ctx_mgr:
            terminal_reason = emit_chain_budget_unused_if_remaining(
                session_id="budget-exhausted",
                chain_step=3,
                max_chain_steps=3,
                skip_memory=skip_memory,
                project="yoke",
            )
        assert terminal_reason == "all_candidates_stale"
        events = [c for c in captured if c["name"] == "ChainBudgetUnused"]
        assert events == []

    def test_returns_none_when_no_skips_this_step(self):
        skip_memory = [
            {"item_id": _sun(1), "skip_reason": "stale_lifecycle", "chain_step": 1},
        ]
        captured, ctx_mgr = self._capture_events()
        with ctx_mgr:
            terminal_reason = emit_chain_budget_unused_if_remaining(
                session_id="budget-other-step",
                chain_step=2,
                max_chain_steps=3,
                skip_memory=skip_memory,
                project="yoke",
            )
        assert terminal_reason is None
        events = [c for c in captured if c["name"] == "ChainBudgetUnused"]
        assert events == []

    def test_filters_skip_entries_to_current_step(self):
        skip_memory = [
            {"item_id": _sun(1), "skip_reason": "stale_lifecycle", "chain_step": 1},
            {"item_id": _sun(2), "skip_reason": "live_claim_conflict", "chain_step": 2},
        ]
        captured, ctx_mgr = self._capture_events()
        with ctx_mgr:
            terminal_reason = emit_chain_budget_unused_if_remaining(
                session_id="budget-filter",
                chain_step=2,
                max_chain_steps=3,
                skip_memory=skip_memory,
                project="yoke",
            )
        assert terminal_reason == "all_candidates_blocked"
        events = [c for c in captured if c["name"] == "ChainBudgetUnused"]
        assert len(events) == 1
        ctx = events[0]["context"]
        trail = ctx["candidate_trail"]
        assert [entry["item_id"] for entry in trail] == [_sun(2)]
        assert trail[0]["skip_reason"] == "live_claim_conflict"

    def test_mixed_reasons_emit_mixed_unavailable(self):
        skip_memory = [
            {"item_id": _sun(1), "skip_reason": "stale_lifecycle", "chain_step": 1},
            {"item_id": _sun(2), "skip_reason": "live_claim_conflict", "chain_step": 1},
        ]
        captured, ctx_mgr = self._capture_events()
        with ctx_mgr:
            terminal_reason = emit_chain_budget_unused_if_remaining(
                session_id="budget-mixed",
                chain_step=1,
                max_chain_steps=3,
                skip_memory=skip_memory,
                project="yoke",
            )
        assert terminal_reason == "mixed_unavailable"
        events = [c for c in captured if c["name"] == "ChainBudgetUnused"]
        assert len(events) == 1
        assert events[0]["context"]["terminal_reason"] == "mixed_unavailable"
