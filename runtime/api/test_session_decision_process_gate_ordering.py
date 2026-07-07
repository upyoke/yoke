"""Ordering regressions for process-offer gate policy and lane filters.

When a process action is blocked by both
the global ``do_process_offer_*`` policy AND the lane allowlist, the
policy gate wins. The operator-facing reason names the load-bearing
config key: switching lanes cannot unblock a globally-disabled
process. Lane WAIT is reserved for the case where the global policy
*enables* the process but the lane allowlist excludes the path.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from yoke_core.domain.session_contract import (
    ActionKind,
    FrontierState,
    NextAction,
)
from yoke_core.domain.session_decision_process_gate import (
    apply_process_offer_gate,
)
from yoke_core.api.routing_config import ProcessOfferPolicy


def _make_action(kind: ActionKind, **kwargs) -> NextAction:
    return NextAction(
        action=kind,
        reason=kwargs.pop("reason", f"{kind.value} test"),
        chainable=kwargs.pop("chainable", False),
        correlation_id=kwargs.pop("correlation_id", "ordering-sess"),
        context=kwargs.pop("context", {}),
    )


def _drift_frontier(
    *, runnable_items=None, sml_coherent=True,
) -> FrontierState:
    return FrontierState(
        sml_coherent=sml_coherent,
        runnable_items=runnable_items or [],
        scheduler_context={} if runnable_items else None,
        drift_review={
            "classification": "both",
            "summary": "ordering test",
            "checkpoint_start": "",
            "reviewed_through": "",
            "delivered_items": [],
        },
    )


class TestPolicyWinsWhenBothGatesBlock:
    """Global policy disable wins over lane block."""

    def test_strategize_disabled_policy_wins_over_darius_lane(self):
        # Reproduces a drift-review offer where STRATEGIZE is globally
        # disabled and the lane allowlist excludes 'strategize'. The
        # policy branch wins and returns the suppressed-WAIT shape
        # naming the load-bearing config key.
        result = apply_process_offer_gate(
            _make_action(
                ActionKind.STRATEGIZE,
                reason="Drift review: both SML and frontier impacted",
                context={"sml_coherent": True},
            ),
            _drift_frontier(runnable_items=[]),
            "ordering-corr",
            ProcessOfferPolicy(),  # all process keys disabled by default
            lane_allowed_paths={
                "DARIUS": ["shepherd", "advance", "conduct", "usher"],
            },
            execution_lane="DARIUS",
        )
        # Suppressed-WAIT (process-policy shape), not a lane WAIT.
        assert result.action == ActionKind.WAIT
        assert result.context["wait_reason"] == "process_suppressed_no_alternative"
        suppressed = result.context["suppressed_process_recommendation"]
        assert suppressed["process_key"] == "STRATEGIZE"
        assert suppressed["config_key"] == "do_process_offer_strategize"
        assert suppressed["direct_command"] == "/yoke strategize"
        # Lane WAIT keys must NOT appear — the policy-suppressed shape
        # is distinct from the lane WAIT shape.
        assert "actual_lane" not in result.context
        assert "allowed_paths" not in result.context
        # The operator-facing reason names the config knob, not the lane.
        assert "do_process_offer_strategize" in result.reason
        assert "DARIUS" not in result.reason

    def test_disabled_policy_with_runnable_items_returns_charge_fallback(self):
        # When the global policy is disabled but runnable items exist,
        # the policy-disabled branch returns a CHARGE fallback rather
        # than ESCALATE. Lane block must still NOT win: the charge
        # fallback names the config key in the skipped_process payload.
        frontier = FrontierState(
            sml_coherent=True,
            runnable_items=["ITEM-1700"],
            scheduler_context={
                "selected_item": "ITEM-1700",
                "next_step": "advance",
                "item_type": "issue",
                "status": "refined-idea",
                "title": "downstream item",
                "rank": 1,
                "explanation": "test",
                "adapter": "conduct",
            },
            selected_item="ITEM-1700",
            drift_review={
                "classification": "both",
                "summary": "ordering test",
                "checkpoint_start": "",
                "reviewed_through": "",
                "delivered_items": [],
            },
        )
        result = apply_process_offer_gate(
            _make_action(ActionKind.FEED),
            frontier,
            "ordering-corr",
            ProcessOfferPolicy(),  # FEED disabled
            lane_allowed_paths={"ALTMAN": ["refine", "polish"]},
            execution_lane="ALTMAN",
        )
        assert result.action == ActionKind.CHARGE
        assert result.chainable is True
        assert "skipped_process" in result.context
        skipped = result.context["skipped_process"]
        assert skipped["process_key"] == "FEED"
        assert skipped["config_key"] == "do_process_offer_feed"
        # Lane WAIT shape must NOT appear on the charge fallback.
        assert "wait_reason" not in result.context


class TestLaneWinsWhenPolicyEnabled:
    """AC-2 / AC-5: lane WAIT preserved when the global policy enables the process."""

    def test_lane_block_fires_when_strategize_policy_enabled(self):
        # Inverse of the above: STRATEGIZE is globally enabled, but
        # the lane DARIUS does not include it. Lane gate fires.
        result = apply_process_offer_gate(
            _make_action(
                ActionKind.STRATEGIZE,
                reason="Strategic layer needs attention",
                context={"sml_coherent": False},
            ),
            _drift_frontier(runnable_items=[]),
            "ordering-corr",
            ProcessOfferPolicy(per_process={"strategize": True}),
            lane_allowed_paths={
                "DARIUS": ["shepherd", "advance", "conduct", "usher"],
            },
            execution_lane="DARIUS",
        )
        assert result.action == ActionKind.WAIT
        assert result.context["wait_reason"] == "lane_policy_disallows_path"
        assert result.context["actual_lane"] == "DARIUS"
        assert result.context["required_path"] == "strategize"
        # The disabled-process markers must NOT appear on the lane WAIT.
        assert "process_disabled" not in result.context
        assert "config_key" not in result.context

    def test_no_policy_preserves_lane_block(self):
        # Backward-compat path: when ``policy`` is None, the lane gate
        # is the only filter. Lane block must still fire.
        result = apply_process_offer_gate(
            _make_action(ActionKind.FEED),
            _drift_frontier(runnable_items=[]),
            "ordering-corr",
            policy=None,
            lane_allowed_paths={"ALTMAN": ["refine", "polish"]},
            execution_lane="ALTMAN",
        )
        assert result.action == ActionKind.WAIT
        assert result.context["wait_reason"] == "lane_policy_disallows_path"


class TestPolicyEnabledLaneAllows:
    """AC-2: when both gates pass, the original action proceeds unchanged."""

    def test_action_passes_through_when_policy_and_lane_permit(self):
        original = _make_action(
            ActionKind.FEED,
            reason="materialize more work",
        )
        result = apply_process_offer_gate(
            original,
            _drift_frontier(runnable_items=[]),
            "ordering-corr",
            ProcessOfferPolicy(per_process={"feed": True}),
            lane_allowed_paths={"ALTMAN": ["feed", "refine"]},
            execution_lane="ALTMAN",
        )
        assert result is original
