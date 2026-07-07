"""Tests for yoke_core.domain.session — lane path-policy routing."""

from __future__ import annotations

import os
import sys
from runtime.api.test_constants import TEST_MODEL_ID

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from yoke_core.domain.session import (
    ActionKind,
    FrontierState,
    SessionOffer,
    decide_next_action,
)


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


class TestLaneRouting:
    """Lane routing: configured lane policies gate downstream paths;
    scheduler steps do not carry a lane assignment."""

    def _frontier_with_step(self, next_step: str = "refine") -> FrontierState:
        return FrontierState(
            runnable_items=["YOK-10"],
            sml_coherent=True,
            selected_item="YOK-10",
            scheduler_context={
                "next_step": next_step,
                "item_type": "issue",
                "status": "idea",
                "title": "Test",
                "rank": 0,
                "explanation": "test",
                "adapter": next_step,
            },
        )

    def test_no_legacy_gate_without_lane_policy(self):
        """Without lane_allowed_paths, any lane can charge any step (no legacy gate)."""
        offer = _make_offer(execution_lane="DARIUS")
        frontier = self._frontier_with_step(next_step="refine")
        result = decide_next_action(offer, frontier)
        assert result.action == ActionKind.CHARGE

    def test_unknown_lane_waits_with_lane_policy_unknown(self):
        """unknown lane no longer fails open — emits WAIT with lane_policy_unknown."""
        offer = _make_offer(execution_lane="UNKNOWN_LANE")
        frontier = self._frontier_with_step(next_step="advance")
        result = decide_next_action(
            offer,
            frontier,
            lane_allowed_paths={
                "DARIUS": ["advance", "conduct", "shepherd", "usher"],
                "ALTMAN": ["refine", "polish"],
            },
        )
        assert result.action == ActionKind.WAIT
        assert result.context["wait_reason"] == "lane_policy_unknown"
        assert result.context["unknown_lane"] == "UNKNOWN_LANE"
        assert result.context["configured_lanes"] == ["ALTMAN", "DARIUS"]

    def test_altman_session_charges_refine(self):
        """ALTMAN session charges normally for refine."""
        offer = _make_offer(execution_lane="ALTMAN")
        frontier = self._frontier_with_step(next_step="refine")
        result = decide_next_action(offer, frontier)
        assert result.action == ActionKind.CHARGE

    def test_altman_session_charges_polish(self):
        """ALTMAN session charges normally for polish."""
        offer = _make_offer(execution_lane="ALTMAN")
        frontier = self._frontier_with_step(next_step="polish")
        result = decide_next_action(offer, frontier)
        assert result.action == ActionKind.CHARGE

    def test_any_lane_charges_any_step_without_policy(self):
        """Without lane policy, the current lane does not compare against scheduler lane metadata."""
        offer = _make_offer(execution_lane="ALTMAN")
        frontier = self._frontier_with_step(next_step="advance")
        result = decide_next_action(offer, frontier)
        assert result.action == ActionKind.CHARGE

    def test_charges_when_path_allowed(self):
        """Path-allowed charge succeeds."""
        offer = _make_offer(execution_lane="DARIUS")
        frontier = self._frontier_with_step(next_step="advance")
        result = decide_next_action(offer, frontier)
        assert result.action == ActionKind.CHARGE

    def test_configured_lane_policy_waits_when_path_not_allowed(self):
        """Config-backed lane allowlists hard-block disallowed downstream paths."""
        offer = _make_offer(execution_lane="ALTMAN")
        frontier = self._frontier_with_step(next_step="advance")
        result = decide_next_action(
            offer,
            frontier,
            lane_allowed_paths={
                "DARIUS": ["advance", "conduct", "shepherd", "usher"],
                "ALTMAN": ["refine", "polish"],
            },
        )
        assert result.action == ActionKind.WAIT
        assert result.context["wait_reason"] == "lane_policy_disallows_path"
        assert result.context["required_path"] == "advance"
        assert result.context["allowed_paths"] == ["refine", "polish"]

    def test_configured_lane_policy_charges_when_actual_lane_allows_path(self):
        """Configured path allowances decide charge without preferred-lane metadata."""
        offer = _make_offer(execution_lane="ALTMAN")
        frontier = self._frontier_with_step(next_step="advance")
        result = decide_next_action(
            offer,
            frontier,
            lane_allowed_paths={
                "DARIUS": ["advance", "conduct", "shepherd", "usher"],
                "ALTMAN": ["refine", "polish", "advance"],
            },
        )
        assert result.action == ActionKind.CHARGE

    def test_unconfigured_lane_waits_with_lane_policy_unknown(self):
        """unconfigured lane no longer fails open — emits WAIT with lane_policy_unknown."""
        offer = _make_offer(execution_lane="ALTMAN-REVIEW")
        frontier = self._frontier_with_step(next_step="advance")
        result = decide_next_action(
            offer,
            frontier,
            lane_allowed_paths={
                "DARIUS": ["advance", "conduct", "shepherd", "usher"],
                "ALTMAN": ["refine", "polish"],
            },
        )
        assert result.action == ActionKind.WAIT
        assert result.context["wait_reason"] == "lane_policy_unknown"
        assert result.context["unknown_lane"] == "ALTMAN_REVIEW"
