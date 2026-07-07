"""Unit coverage for the shared lane-policy gate evaluator.

Covers AC-3, AC-6, AC-12
* the evaluator returns one of three verdicts (ALLOWED,
  WAIT_DISALLOWED, WAIT_UNKNOWN),
* the four canonical lane shapes against the policy gate
  (DARIUS+polish, ALTMAN+polish, unknown lane, empty / NULL lane),
* the helper is consulted by ``decide_charge_action``,
  ``decide_resume_action``, and ``apply_process_offer_gate`` (the
  three call sites listed in AC-12).
"""

from __future__ import annotations

from typing import Dict, List

import pytest

from yoke_core.domain.session_contract import (
    ActionKind,
    ClaimedWork,
    FrontierState,
    NextAction,
    SessionOffer,
)
from yoke_core.domain.session_decision import decide_next_action
from yoke_core.domain.session_decision_charge import decide_charge_action
from yoke_core.domain.session_decision_lane_gate import (
    LaneGateResult,
    LaneGateVerdict,
    evaluate_lane_gate,
)
from yoke_core.domain.session_decision_resume import decide_resume_action


CANONICAL_POLICY: Dict[str, List[str]] = {
    "DARIUS": ["shepherd", "advance", "conduct", "usher"],
    "ALTMAN": ["refine", "polish"],
}


def _offer(execution_lane: str = "DARIUS", **overrides) -> SessionOffer:
    defaults = {
        "session_id": "lane-gate-sess",
        "executor": "claude-code",
        "provider": "anthropic",
        "model": "claude-opus-4-7",
        "workspace": "/tmp/yoke",
        "execution_lane": execution_lane,
    }
    defaults.update(overrides)
    return SessionOffer(**defaults)


def _frontier_with_step(next_step: str) -> FrontierState:
    return FrontierState(
        runnable_items=["YOK-10"],
        sml_coherent=True,
        selected_item="YOK-10",
        scheduler_context={
            "next_step": next_step,
            "item_type": "issue",
            "status": "reviewed-implementation",
            "title": "Test",
            "rank": 0,
            "explanation": "test",
            "adapter": next_step,
        },
    )


class TestEvaluateLaneGate:
    """Pure evaluator unit coverage — verdict + context shape."""

    def test_no_policy_fails_open(self):
        result = evaluate_lane_gate(
            execution_lane="DARIUS",
            required_path="advance",
            lane_allowed_paths=None,
        )
        assert result.verdict is LaneGateVerdict.ALLOWED

    def test_empty_policy_fails_open(self):
        result = evaluate_lane_gate(
            execution_lane="DARIUS",
            required_path="advance",
            lane_allowed_paths={},
        )
        assert result.verdict is LaneGateVerdict.ALLOWED

    def test_no_required_path_passes(self):
        result = evaluate_lane_gate(
            execution_lane="DARIUS",
            required_path=None,
            lane_allowed_paths=CANONICAL_POLICY,
        )
        assert result.verdict is LaneGateVerdict.ALLOWED

    def test_darius_polish_disallowed(self):
        result = evaluate_lane_gate(
            execution_lane="DARIUS",
            required_path="polish",
            lane_allowed_paths=CANONICAL_POLICY,
        )
        assert result.verdict is LaneGateVerdict.WAIT_DISALLOWED
        assert result.allowed_paths == ["shepherd", "advance", "conduct", "usher"]
        ctx = result.wait_context()
        assert ctx["wait_reason"] == "lane_policy_disallows_path"
        assert ctx["required_path"] == "polish"
        assert ctx["allowed_paths"] == ["shepherd", "advance", "conduct", "usher"]

    def test_altman_polish_allowed(self):
        result = evaluate_lane_gate(
            execution_lane="ALTMAN",
            required_path="polish",
            lane_allowed_paths=CANONICAL_POLICY,
        )
        assert result.verdict is LaneGateVerdict.ALLOWED

    def test_unknown_lane_returns_wait_unknown(self):
        """previously fail-open. Now WAIT_UNKNOWN."""
        result = evaluate_lane_gate(
            execution_lane="primary",
            required_path="polish",
            lane_allowed_paths=CANONICAL_POLICY,
        )
        assert result.verdict is LaneGateVerdict.WAIT_UNKNOWN
        ctx = result.wait_context()
        assert ctx["wait_reason"] == "lane_policy_unknown"
        assert ctx["unknown_lane"] == "PRIMARY"
        assert ctx["configured_lanes"] == ["ALTMAN", "DARIUS"]

    def test_empty_lane_returns_wait_unknown(self):
        result = evaluate_lane_gate(
            execution_lane="",
            required_path="polish",
            lane_allowed_paths=CANONICAL_POLICY,
        )
        assert result.verdict is LaneGateVerdict.WAIT_UNKNOWN

    def test_none_lane_returns_wait_unknown(self):
        result = evaluate_lane_gate(
            execution_lane=None,
            required_path="polish",
            lane_allowed_paths=CANONICAL_POLICY,
        )
        assert result.verdict is LaneGateVerdict.WAIT_UNKNOWN


class TestFourCanonicalShapesViaDecideCharge:
    """AC-6 — DARIUS+polish, ALTMAN+polish, unknown, empty across charge."""

    def test_darius_polish_waits_disallowed(self):
        result = decide_charge_action(
            _offer(execution_lane="DARIUS"),
            _frontier_with_step("polish"),
            correlation="corr",
            lane_allowed_paths=CANONICAL_POLICY,
        )
        assert result is not None
        assert result.action == ActionKind.WAIT
        assert result.context["wait_reason"] == "lane_policy_disallows_path"

    def test_altman_polish_charges(self):
        result = decide_charge_action(
            _offer(execution_lane="ALTMAN"),
            _frontier_with_step("polish"),
            correlation="corr",
            lane_allowed_paths=CANONICAL_POLICY,
        )
        assert result is not None
        assert result.action == ActionKind.CHARGE

    def test_unknown_lane_waits_lane_policy_unknown(self):
        result = decide_charge_action(
            _offer(execution_lane="primary"),
            _frontier_with_step("polish"),
            correlation="corr",
            lane_allowed_paths=CANONICAL_POLICY,
        )
        assert result is not None
        assert result.action == ActionKind.WAIT
        assert result.context["wait_reason"] == "lane_policy_unknown"
        assert result.context["unknown_lane"] == "PRIMARY"

    def test_empty_lane_waits_lane_policy_unknown(self):
        result = decide_charge_action(
            _offer(execution_lane=""),
            _frontier_with_step("polish"),
            correlation="corr",
            lane_allowed_paths=CANONICAL_POLICY,
        )
        assert result is not None
        assert result.action == ActionKind.WAIT
        assert result.context["wait_reason"] == "lane_policy_unknown"


class TestFourCanonicalShapesViaDecideResume:
    """AC-6 — DARIUS+polish, ALTMAN+polish, unknown, empty across resume."""

    def _claim(self, required_path: str) -> ClaimedWork:
        return ClaimedWork(
            item_id="YOK-10",
            status="polishing-implementation",
            required_path=required_path,
        )

    def test_darius_polish_waits_disallowed(self):
        result = decide_resume_action(
            _offer(execution_lane="DARIUS"),
            FrontierState(),
            self._claim("polish"),
            correlation="corr",
            lane_allowed_paths=CANONICAL_POLICY,
        )
        assert result.action == ActionKind.WAIT
        assert result.context["wait_reason"] == "lane_policy_disallows_path"

    def test_altman_polish_resumes(self):
        result = decide_resume_action(
            _offer(execution_lane="ALTMAN"),
            FrontierState(),
            self._claim("polish"),
            correlation="corr",
            lane_allowed_paths=CANONICAL_POLICY,
        )
        assert result.action == ActionKind.RESUME

    def test_unknown_lane_waits_lane_policy_unknown(self):
        result = decide_resume_action(
            _offer(execution_lane="primary"),
            FrontierState(),
            self._claim("polish"),
            correlation="corr",
            lane_allowed_paths=CANONICAL_POLICY,
        )
        assert result.action == ActionKind.WAIT
        assert result.context["wait_reason"] == "lane_policy_unknown"

    def test_empty_lane_waits_lane_policy_unknown(self):
        result = decide_resume_action(
            _offer(execution_lane=""),
            FrontierState(),
            self._claim("polish"),
            correlation="corr",
            lane_allowed_paths=CANONICAL_POLICY,
        )
        assert result.action == ActionKind.WAIT
        assert result.context["wait_reason"] == "lane_policy_unknown"


class TestRegressionDariusPolishViaDecideNextAction:
    """AC-5 regression: replay chain-step-2 of session ``1776a63a-...``.

    A DARIUS-lane session with an ``--lane primary`` offer would
    previously route ``polish`` for the selected item. Afterwards,
    ``decide_charge_action`` must filter the polish candidate and
    return WAIT or otherwise refuse to route the action — both
    branches are acceptable for AC-5; the contract is "does not
    return CHARGE for polish on this lane".
    """

    def test_polish_not_routed_for_darius_lane(self):
        # The offering session's execution_lane on the row is DARIUS
        # (per the regression fixture). After the the server reads
        # the row and the decision engine sees DARIUS — not 'primary'.
        offer = _offer(execution_lane="DARIUS")
        frontier = _frontier_with_step("polish")
        result = decide_next_action(
            offer,
            frontier,
            lane_allowed_paths=CANONICAL_POLICY,
        )
        assert result.action != ActionKind.CHARGE
        if result.action == ActionKind.WAIT:
            assert result.context["wait_reason"] in (
                "lane_policy_disallows_path",
                "lane_policy_unknown",
            )

    def test_polish_routed_for_altman_lane(self):
        offer = _offer(execution_lane="ALTMAN")
        frontier = _frontier_with_step("polish")
        result = decide_next_action(
            offer,
            frontier,
            lane_allowed_paths=CANONICAL_POLICY,
        )
        assert result.action == ActionKind.CHARGE
