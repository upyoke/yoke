"""Tests for yoke_core.domain.session — do-loop contract + decision priority.

Shared residual suite: do-loop orchestration contract assertions and
decision priority ordering against ``decide_next_action``.

Focused unit tests live in child files:
  - test_session_imports.py: import-hygiene smoke tests and the
    SessionOffer.supported_paths field shape
  - test_session_start_*: SessionOffer, NextAction, ActionKind, FrontierState,
    ClaimedWork, decide_next_action (resume/charge/feed/strategize/escalate/wait paths)
  - test_session_render_{routing,lane,resume}.py: path derivation, lane routing,
    drift-review routing, resume compatibility, no-progress detection
"""

from __future__ import annotations


import os
import sys
from pathlib import Path
from runtime.api.test_constants import TEST_MODEL_ID

# Ensure the repo root is importable
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

_REPO_ROOT = Path(__file__).resolve().parents[2]


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


# ---------------------------------------------------------------------------
# decide_next_action — priority ordering comprehensive
# ---------------------------------------------------------------------------


class TestDecisionPriorityOrdering:
    """Verify the strict priority ordering: resume > charge > escalate > feed (graph stale) > feed (no items) > strategize > wait."""

    def test_resume_beats_everything(self):
        """Resume wins even with runnable items, blocked items, and incoherent SML."""
        offer = _make_offer()
        frontier = FrontierState(
            runnable_items=["YOK-1"],
            blocked_items=["YOK-2"],
            sml_coherent=False,
        )
        claims = [ClaimedWork(item_id="YOK-99", status="active")]
        result = decide_next_action(offer, frontier, claims)
        assert result.action == ActionKind.RESUME

    def test_charge_beats_escalate_feed_strategize(self):
        """When runnable items and coherent SML, charge wins."""
        offer = _make_offer()
        frontier = FrontierState(
            runnable_items=["YOK-1"],
            blocked_items=["YOK-2"],
            sml_coherent=True,
        )
        result = decide_next_action(offer, frontier)
        assert result.action == ActionKind.CHARGE

    def test_escalate_beats_feed_and_strategize(self):
        """When all items are blocked (no runnable), escalate wins over feed/strategize."""
        offer = _make_offer()
        frontier = FrontierState(
            runnable_items=[],
            blocked_items=["YOK-5"],
            sml_coherent=True,
        )
        result = decide_next_action(offer, frontier)
        assert result.action == ActionKind.ESCALATE

    def test_feed_beats_strategize_when_coherent(self):
        """Empty frontier + coherent SML -> feed (not strategize)."""
        offer = _make_offer()
        frontier = FrontierState(
            runnable_items=[],
            blocked_items=[],
            sml_coherent=True,
        )
        result = decide_next_action(offer, frontier)
        assert result.action == ActionKind.FEED

    def test_strategize_when_sml_broken(self):
        """Incoherent SML with empty frontier -> strategize."""
        offer = _make_offer()
        frontier = FrontierState(
            runnable_items=[],
            blocked_items=[],
            sml_coherent=False,
        )
        result = decide_next_action(offer, frontier)
        assert result.action == ActionKind.STRATEGIZE

    def test_escalate_includes_all_blocked_items(self):
        """Escalate context should list all blocked items."""
        offer = _make_offer()
        frontier = FrontierState(
            runnable_items=[],
            blocked_items=["YOK-1", "YOK-2", "YOK-3"],
            sml_coherent=True,
        )
        result = decide_next_action(offer, frontier)
        assert result.action == ActionKind.ESCALATE
        assert len(result.context["blocked_items"]) == 3

    def test_feed_context_includes_blocked_count(self):
        """Feed context blocked_count should be 0 when no blocked items."""
        offer = _make_offer()
        frontier = FrontierState(
            runnable_items=[],
            blocked_items=[],
            sml_coherent=True,
        )
        result = decide_next_action(offer, frontier)
        assert result.action == ActionKind.FEED
        assert result.context["blocked_count"] == 0

    def test_strategize_context_includes_sml_coherent(self):
        """Strategize context should include sml_coherent."""
        offer = _make_offer()
        frontier = FrontierState(sml_coherent=False)
        result = decide_next_action(offer, frontier)
        assert result.action == ActionKind.STRATEGIZE
        assert result.context["sml_coherent"] is False
