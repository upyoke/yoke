"""AC-6 — four canonical lane shapes across the process-offer gate.

Sibling of :mod:`runtime.api.test_session_decision_lane_gate`; split out
so the host test file stays under the 350-line authored-file cap. The
process-gate path uses distinct path tokens (``feed``, ``strategize``)
so it carries its own POLICY constant rather than reusing the
lifecycle-path one from the host file.
"""

from __future__ import annotations

from typing import Dict, List

from yoke_core.domain.session_contract import (
    ActionKind,
    FrontierState,
    NextAction,
)
from yoke_core.domain.session_decision_process_gate import (
    apply_process_offer_gate,
)
from yoke_core.api.routing_config import ProcessOfferPolicy


PROCESS_POLICY: Dict[str, List[str]] = {
    "DARIUS": ["shepherd", "advance", "conduct", "usher"],
    "ALTMAN": ["refine", "polish", "feed"],
}


def _action() -> NextAction:
    return NextAction(
        action=ActionKind.FEED,
        reason="feed test",
        chainable=False,
        correlation_id="corr",
    )


def _drift_frontier() -> FrontierState:
    return FrontierState(
        sml_coherent=True,
        runnable_items=[],
        scheduler_context=None,
    )


def _policy_allowing_feed() -> ProcessOfferPolicy:
    return ProcessOfferPolicy(per_process={"feed": True})


class TestFourCanonicalShapesViaProcessGate:
    """Mirrors lifecycle-path coverage for the process-gate path."""

    def test_darius_feed_waits_disallowed(self):
        result = apply_process_offer_gate(
            _action(),
            _drift_frontier(),
            "corr",
            _policy_allowing_feed(),
            lane_allowed_paths=PROCESS_POLICY,
            execution_lane="DARIUS",
        )
        assert result.action == ActionKind.WAIT
        assert result.context["wait_reason"] == "lane_policy_disallows_path"

    def test_altman_feed_passes_through(self):
        action = _action()
        result = apply_process_offer_gate(
            action,
            _drift_frontier(),
            "corr",
            _policy_allowing_feed(),
            lane_allowed_paths=PROCESS_POLICY,
            execution_lane="ALTMAN",
        )
        assert result is action

    def test_unknown_lane_waits_lane_policy_unknown(self):
        result = apply_process_offer_gate(
            _action(),
            _drift_frontier(),
            "corr",
            _policy_allowing_feed(),
            lane_allowed_paths=PROCESS_POLICY,
            execution_lane="primary",
        )
        assert result.action == ActionKind.WAIT
        assert result.context["wait_reason"] == "lane_policy_unknown"

    def test_empty_lane_waits_lane_policy_unknown(self):
        result = apply_process_offer_gate(
            _action(),
            _drift_frontier(),
            "corr",
            _policy_allowing_feed(),
            lane_allowed_paths=PROCESS_POLICY,
            execution_lane="",
        )
        assert result.action == ActionKind.WAIT
        assert result.context["wait_reason"] == "lane_policy_unknown"
